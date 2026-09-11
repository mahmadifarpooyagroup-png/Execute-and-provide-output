from __future__ import annotations

import os
import sqlite3
import uuid


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
        for column, definition in (
            ("confirmed_at", "TIMESTAMP"),
            ("expires_at", "TIMESTAMP"),
            ("claim_owner", "TEXT"),
            ("attempt", "INTEGER NOT NULL DEFAULT 0"),
            ("operation_id", "TEXT"),
        ):
            self._add_column_if_missing(conn, "idempotency_ledger", column, definition)

        for column, definition in (
            ("provider_profile_id", "TEXT"),
            ("fencing_token", "INTEGER"),
            ("operation_id", "TEXT"),
            ("side_effecting", "INTEGER NOT NULL DEFAULT 1"),
        ):
            self._add_column_if_missing(conn, "steps", column, definition)

        self._add_column_if_missing(conn, "workflow_checkpoints", "revision", "INTEGER NOT NULL DEFAULT 0")
        self._add_column_if_missing(conn, "workflows", "client_request_id", "TEXT")
        for column, definition in (
            ("path", "TEXT"),
            ("sha256", "TEXT"),
            ("updated_at", "TIMESTAMP"),
        ):
            self._add_column_if_missing(conn, "plugins_registry", column, definition)

        self._backfill_operation_ids(conn)
        self._repair_duplicate_request_ids(conn)

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_workflows_client_request_id ON workflows(client_request_id) WHERE client_request_id IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_steps_operation_id ON steps(operation_id) WHERE operation_id IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_workflow_step ON idempotency_ledger(workflow_id, step_id, provider_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_expiry ON idempotency_ledger(status, expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_operation ON idempotency_ledger(operation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_steps_workflow_order ON steps(task_id, order_index)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_owner_expiry ON sessions(lock_owner, lease_expiry)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plugins_active ON plugins_registry(is_active)")

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

    def purge_workflows_older_than(self, retention_days: int) -> int:
        """
        FIX (بند ۲/۱۵): retentionDays was a stored setting with no real
        consumer. This housekeeping routine deletes terminal workflows
        (COMPLETED/CANCELLED/FAILED) older than retention_days, along with
        their dependent rows, in FK-safe order (children before parents).
        Returns the number of workflows deleted.
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

            placeholders = ",".join("?" for _ in stale_ids)
            # Children before parents to satisfy foreign_keys=ON
            conn.execute(
                f"DELETE FROM steps WHERE task_id IN "
                f"(SELECT task_id FROM tasks WHERE workflow_id IN ({placeholders}))",
                stale_ids,
            )
            conn.execute(f"DELETE FROM tasks WHERE workflow_id IN ({placeholders})", stale_ids)
            conn.execute(f"DELETE FROM workflow_checkpoints WHERE workflow_id IN ({placeholders})", stale_ids)
            conn.execute(f"DELETE FROM idempotency_ledger WHERE workflow_id IN ({placeholders})", stale_ids)
            conn.execute(f"DELETE FROM external_operations WHERE workflow_id IN ({placeholders})", stale_ids)
            conn.execute(f"DELETE FROM audit_log WHERE workflow_id IN ({placeholders})", stale_ids)
            conn.execute(f"DELETE FROM sync_metadata WHERE workflow_id IN ({placeholders})", stale_ids)
            conn.execute(f"DELETE FROM workflows WHERE workflow_id IN ({placeholders})", stale_ids)
            conn.commit()
            return len(stale_ids)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
