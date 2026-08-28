"""Database layer for Atrin AI Control Plane.

Implements SQLite with WAL mode per Section 48, and creates:
- idempotency_ledger table per Section 35.1
- audit_log table with tamper-evident hash chain per Section 42.1
"""

import sqlite3
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


class AtrinDatabase:
    """SQLite database wrapper with WAL mode and required tables."""
    
    def __init__(self, db_path: str = ":memory:"):
        """Initialize the database connection.
        
        Args:
            db_path: Path to SQLite database file, or ":memory:" for in-memory DB.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._enable_wal()
        self._create_tables()
    
    def _enable_wal(self) -> None:
        """Enable WAL journal mode per Section 48."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        self.conn.commit()
    
    def _create_tables(self) -> None:
        """Create required tables."""
        cursor = self.conn.cursor()
        
        # Idempotency ledger per Section 35.1
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_ledger (
                idempotency_key TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING', 'CONFIRMED', 'FAILED')),
                external_ref TEXT,
                created_at TEXT NOT NULL,
                confirmed_at TEXT,
                expires_at TEXT NOT NULL
            )
        """)
        
        # Audit log with tamper-evident hash chain per Section 42.1
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                workflow_id TEXT,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT,
                entry_hash TEXT NOT NULL
            )
        """)
        
        self.conn.commit()
    
    def _compute_entry_hash(
        self,
        prev_hash: Optional[str],
        payload: str,
        timestamp: str
    ) -> str:
        """Compute entry hash for tamper-evident chain.
        
        entry_hash = hash(prev_hash || payload || timestamp)
        """
        data = f"{prev_hash or ''}{payload}{timestamp}"
        return hashlib.sha256(data.encode('utf-8')).hexdigest()
    
    def get_last_entry_hash(self) -> Optional[str]:
        """Get the hash of the last audit log entry."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None
    
    def append_audit_log(
        self,
        workflow_id: Optional[str],
        event_type: str,
        actor: str,
        payload: dict
    ) -> int:
        """Append an entry to the audit log with hash chaining.
        
        Returns the sequence number of the inserted entry.
        """
        cursor = self.conn.cursor()
        timestamp = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, sort_keys=True)
        prev_hash = self.get_last_entry_hash()
        entry_hash = self._compute_entry_hash(prev_hash, payload_json, timestamp)
        
        cursor.execute("""
            INSERT INTO audit_log (timestamp, workflow_id, event_type, actor, payload, prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, workflow_id, event_type, actor, payload_json, prev_hash, entry_hash))
        
        self.conn.commit()
        return cursor.lastrowid
    
    def insert_idempotency_record(
        self,
        idempotency_key: str,
        workflow_id: str,
        step_id: str,
        provider_id: str,
        status: str,
        external_ref: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> None:
        """Insert a record into the idempotency ledger."""
        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc)
        if expires_at is None:
            # Default: 30 days from creation per Section 35.1
            from datetime import timedelta
            expires_at = now + timedelta(days=30)
        
        cursor.execute("""
            INSERT OR REPLACE INTO idempotency_ledger 
            (idempotency_key, workflow_id, step_id, provider_id, status, external_ref, created_at, confirmed_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            idempotency_key,
            workflow_id,
            step_id,
            provider_id,
            status,
            external_ref,
            now.isoformat(),
            now.isoformat() if status == 'CONFIRMED' else None,
            expires_at.isoformat()
        ))
        
        self.conn.commit()
    
    def get_idempotency_record(self, idempotency_key: str) -> Optional[dict]:
        """Retrieve an idempotency record by key."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT idempotency_key, workflow_id, step_id, provider_id, status, 
                   external_ref, created_at, confirmed_at, expires_at
            FROM idempotency_ledger
            WHERE idempotency_key = ?
        """, (idempotency_key,))
        
        row = cursor.fetchone()
        if row:
            return {
                'idempotency_key': row[0],
                'workflow_id': row[1],
                'step_id': row[2],
                'provider_id': row[3],
                'status': row[4],
                'external_ref': row[5],
                'created_at': row[6],
                'confirmed_at': row[7],
                'expires_at': row[8]
            }
        return None
    
    def check_journal_mode(self) -> str:
        """Check the current journal mode."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        return cursor.fetchone()[0]
    
    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
