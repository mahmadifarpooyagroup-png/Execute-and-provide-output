from __future__ import annotations

import os
import sqlite3
import uuid
from typing import Callable


class AtrinDatabase:
    """SQLite persistence with per-connection safety pragmas and additive migrations."""

    CURRENT_SCHEMA_VERSION = 6

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}

    @classmethod
    def _add_column_if_missing(cls, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        if column not in cls._columns(conn, table):
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')

    def _ensure_migrations_table(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _applied_migrations(self, conn: sqlite3.Connection) -> set[str]:
        return {row["id"] for row in conn.execute("SELECT id FROM schema_migrations").fetchall()}

    def _apply_migration(
        self, conn: sqlite3.Connection, applied: set[str], migration_id: str,
        apply_fn: "Callable[[sqlite3.Connection], object]",
    ) -> None:
        """
        Run a single named, idempotent migration step and record it in the
        schema_migrations ledger. Existing additive schema primitives remain
        safe, so legacy databases can be retroactively marked as migrated.
        """
        if migration_id in applied:
            return
        apply_fn(conn)
        conn.execute(
            "INSERT INTO schema_migrations (id) VALUES (?) ON CONFLICT(id) DO NOTHING",
            (migration_id,),
        )
        applied.add(migration_id)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_ledger (
                idempotency_key TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                operation_id TEXT,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                expires_at TIMESTAMP,
                claim_owner TEXT,
                attempt INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS external_operations (
                idempotency_key  TEXT NOT NULL,
                workflow_id      TEXT NOT NULL,
                step_id          TEXT NOT NULL,
                provider_id      TEXT NOT NULL,
                adapter_type     TEXT NOT NULL,
                operation_id     TEXT,
                external_id      TEXT,
                external_status  TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (idempotency_key, workflow_id, step_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                workflow_id TEXT,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload TEXT,
                prev_hash TEXT,
                entry_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_profiles (
                id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                name TEXT NOT NULL,
                auth_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                fencing_token INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                provider_profile_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'NOT_AUTHENTICATED',
                lock_owner TEXT,
                lease_expiry REAL,
                fencing_token INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provider_profile_id) REFERENCES provider_profiles(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                state TEXT NOT NULL,
                plan_version INTEGER NOT NULL DEFAULT 1,
                client_request_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                order_index INTEGER NOT NULL,
                FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS steps (
                step_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                action TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                operation_id TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING',
                result TEXT,
                evidence TEXT,
                order_index INTEGER NOT NULL,
                provider_profile_id TEXT,
                fencing_token INTEGER,
                side_effecting INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                workflow_id TEXT PRIMARY KEY,
                checkpoint_version INTEGER NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                workflow_id TEXT PRIMARY KEY,
                remote_id TEXT NOT NULL,
                last_synced_at TEXT,
                sync_status TEXT NOT NULL,
                conflict_flag INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plugins_registry (
                plugin_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                path TEXT,
                sha256 TEXT,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _backfill_operation_ids(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT step_id FROM steps WHERE operation_id IS NULL OR operation_id=''"
        ).fetchall()
        for row in rows:
            operation_id = str(uuid.uuid4())
            conn.execute("UPDATE steps SET operation_id=? WHERE step_id=?", (operation_id, row["step_id"]))
        conn.execute("""
            UPDATE idempotency_ledger
            SET operation_id=(
                SELECT s.operation_id FROM steps s
                WHERE s.step_id=idempotency_ledger.step_id
            )
            WHERE operation_id IS NULL OR operation_id=''
        """)

    def _repair_duplicate_request_ids(self, conn: sqlite3.Connection) -> None:
        duplicates = conn.execute("""
            SELECT client_request_id FROM workflows
            WHERE client_request_id IS NOT NULL AND client_request_id != ''
            GROUP BY client_request_id HAVING COUNT(*) > 1
        """).fetchall()
        for duplicate in duplicates:
            rows = conn.execute(
                "SELECT workflow_id FROM workflows WHERE client_request_id=? ORDER BY created_at, workflow_id",
                (duplicate["client_request_id"],),
            ).fetchall()
            for row in rows[1:]:
                conn.execute("UPDATE workflows SET client_request_id=NULL WHERE workflow_id=?", (row["workflow_id"],))

    def _migrate(self, conn: sqlite3.Connection) -> None:
        self._ensure_migrations_table(conn)
        applied = self._applied_migrations(conn)

        self._apply_migration(conn, applied, "001_idempotency_ledger_recovery_columns", lambda c: [
            self._add_column_if_missing(c, "idempotency_ledger", column, definition)
            for column, definition in (
                ("confirmed_at", "TIMESTAMP"),
                ("expires_at", "TIMESTAMP"),
                ("claim_owner", "TEXT"),
                ("attempt", "INTEGER NOT NULL DEFAULT 0"),
                ("operation_id", "TEXT"),
            )
        ])

        self._apply_migration(conn, applied, "002_steps_fencing_and_operation_columns", lambda c: [
            self._add_column_if_missing(c, "steps", column, definition)
            for column, definition in (
                ("provider_profile_id", "TEXT"),
                ("fencing_token", "INTEGER"),
                ("operation_id", "TEXT"),
                ("side_effecting", "INTEGER NOT NULL DEFAULT 1"),
            )
        ])

        self._apply_migration(
            conn, applied, "003_checkpoint_revision_column",
            lambda c: self._add_column_if_missing(c, "workflow_checkpoints", "revision", "INTEGER NOT NULL DEFAULT 0"),
        )

        self._apply_migration(
            conn, applied, "004_workflow_client_request_id_column",
            lambda c: self._add_column_if_missing(c, "workflows", "client_request_id", "TEXT"),
        )

        self._apply_migration(conn, applied, "005_plugins_registry_hash_columns", lambda c: [
            self._add_column_if_missing(c, "plugins_registry", column, definition)
            for column, definition in (
                ("path", "TEXT"),
                ("sha256", "TEXT"),
                ("updated_at", "TIMESTAMP"),
            )
        ])

        self._apply_migration(
            conn, applied, "006_sync_metadata_last_known_remote_revision",
            lambda c: self._add_column_if_missing(c, "sync_metadata", "last_known_remote_revision", "INTEGER"),
        )

        def _migration_007(c: sqlite3.Connection) -> None:
            self._backfill_operation_ids(c)
            self._repair_duplicate_request_ids(c)

        self._apply_migration(conn, applied, "007_backfill_and_repair_ids", _migration_007)

        def _migration_008(c: sqlite3.Connection) -> None:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_workflows_client_request_id ON workflows(client_request_id) WHERE client_request_id IS NOT NULL")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_steps_operation_id ON steps(operation_id) WHERE operation_id IS NOT NULL")
            c.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_workflow_step ON idempotency_ledger(workflow_id, step_id, provider_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_expiry ON idempotency_ledger(status, expires_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_operation ON idempotency_ledger(operation_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_steps_workflow_order ON steps(task_id, order_index)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_owner_expiry ON sessions(lock_owner, lease_expiry)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_plugins_active ON plugins_registry(is_active)")

        self._apply_migration(conn, applied, "008_core_indexes", _migration_008)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO schema_metadata(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(self.CURRENT_SCHEMA_VERSION),),
        )

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = self._configure_connection(sqlite3.connect(self.db_path))
        try:
            self._create_schema(conn)
            self._migrate(conn)
            conn.commit()
        finally:
            conn.close()

    def get_connection(self) -> sqlite3.Connection:
        return self._configure_connection(sqlite3.connect(self.db_path))

    def list_applied_migrations(self) -> list[dict[str, str]]:
        """Return the named schema migrations recorded for this database."""
        connection = self.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, applied_at FROM schema_migrations ORDER BY applied_at, id"
            ).fetchall()
            return [{"id": row["id"], "applied_at": row["applied_at"]} for row in rows]
        finally:
            connection.close()

    def purge_workflows_older_than(self, retention_days: int) -> int:
        """
        Delete terminal workflow data older than retention_days.

        Audit entries are intentionally retained because workflow-engine audit
        records form a global append-only hash chain. Removing a middle entry
        would make validate_audit_chain() report corruption for all later
        entries. Audit retention therefore remains independent from workflow
        data retention.
        """
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")

        conn = self.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cutoff = conn.execute(
                "SELECT datetime('now', ?) AS cutoff", (f"-{int(retention_days)} days",)
            ).fetchone()["cutoff"]

            stale_ids = [
                row["workflow_id"]
                for row in conn.execute(
                    "SELECT workflow_id FROM workflows "
                    "WHERE state IN ('COMPLETED', 'CANCELLED', 'FAILED') AND updated_at < ?",
                    (cutoff,),
                ).fetchall()
            ]
            if not stale_ids:
                conn.commit()
                return 0

            for workflow_id in stale_ids:
                conn.execute(
                    "DELETE FROM steps WHERE task_id IN "
                    "(SELECT task_id FROM tasks WHERE workflow_id=?)",
                    (workflow_id,),
                )
                conn.execute("DELETE FROM tasks WHERE workflow_id=?", (workflow_id,))
                conn.execute("DELETE FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,))
                conn.execute("DELETE FROM idempotency_ledger WHERE workflow_id=?", (workflow_id,))
                conn.execute("DELETE FROM external_operations WHERE workflow_id=?", (workflow_id,))
                # Keep audit_log intact: it is a global hash chain, not child data.
                conn.execute("DELETE FROM sync_metadata WHERE workflow_id=?", (workflow_id,))
                conn.execute("DELETE FROM workflows WHERE workflow_id=?", (workflow_id,))

            conn.commit()
            return len(stale_ids)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
