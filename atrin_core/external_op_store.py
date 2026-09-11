"""
ExternalOperationStore — durable bridge between adapter memory and SQLite.

Fixes (بند ۹، ۱۰، ۱۱ گزارش):
  A2A/ACP/MCP adapters kept their external task/operation IDs only in memory.
  After a process restart verify_action() immediately returned AMBIGUOUS, making
  recovery non-durable.  This module persists the mapping so adapters can
  re-discover the external ID on a fresh process start and poll the real provider.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from .database import AtrinDatabase


class ExternalOperationStore:
    """Thin wrapper around the external_operations table."""

    def __init__(self, db: AtrinDatabase) -> None:
        self.db = db

    # ── write ─────────────────────────────────────────────────────────────────
    def record(
        self,
        *,
        idempotency_key: str,
        workflow_id: str,
        step_id: str,
        provider_id: str,
        adapter_type: str,
        operation_id: Optional[str] = None,
        external_id: Optional[str] = None,
        external_status: Optional[str] = None,
    ) -> None:
        """Upsert an external operation record."""
        conn = self.db.get_connection()
        try:
            conn.execute("""
                INSERT INTO external_operations
                    (idempotency_key, workflow_id, step_id, provider_id,
                     adapter_type, operation_id, external_id, external_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(idempotency_key, workflow_id, step_id) DO UPDATE SET
                    operation_id    = excluded.operation_id,
                    external_id     = excluded.external_id,
                    external_status = excluded.external_status,
                    updated_at      = CURRENT_TIMESTAMP
            """, (idempotency_key, workflow_id, step_id, provider_id,
                  adapter_type, operation_id, external_id, external_status))
            conn.commit()
        finally:
            conn.close()

    def update_status(
        self,
        *,
        idempotency_key: str,
        workflow_id: str,
        step_id: str,
        external_status: str,
        external_id: Optional[str] = None,
    ) -> None:
        """Update status (and optionally external_id) for an existing record."""
        conn = self.db.get_connection()
        try:
            if external_id is not None:
                conn.execute("""
                    UPDATE external_operations
                    SET external_status=?, external_id=?, updated_at=CURRENT_TIMESTAMP
                    WHERE idempotency_key=? AND workflow_id=? AND step_id=?
                """, (external_status, external_id, idempotency_key, workflow_id, step_id))
            else:
                conn.execute("""
                    UPDATE external_operations
                    SET external_status=?, updated_at=CURRENT_TIMESTAMP
                    WHERE idempotency_key=? AND workflow_id=? AND step_id=?
                """, (external_status, idempotency_key, workflow_id, step_id))
            conn.commit()
        finally:
            conn.close()

    # ── read ──────────────────────────────────────────────────────────────────
    def fetch(
        self,
        *,
        idempotency_key: str,
        workflow_id: str,
        step_id: str,
    ) -> Optional[sqlite3.Row]:
        """Return the stored record or None if not found."""
        conn = self.db.get_connection()
        try:
            return conn.execute("""
                SELECT * FROM external_operations
                WHERE idempotency_key=? AND workflow_id=? AND step_id=?
            """, (idempotency_key, workflow_id, step_id)).fetchone()
        finally:
            conn.close()

    def fetch_by_external_id(
        self,
        *,
        external_id: str,
        provider_id: str,
    ) -> Optional[sqlite3.Row]:
        """Look up by provider-side task/job ID (used during recovery scans)."""
        conn = self.db.get_connection()
        try:
            return conn.execute("""
                SELECT * FROM external_operations
                WHERE external_id=? AND provider_id=?
                ORDER BY updated_at DESC LIMIT 1
            """, (external_id, provider_id)).fetchone()
        finally:
            conn.close()
