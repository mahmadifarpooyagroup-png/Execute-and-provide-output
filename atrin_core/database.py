from __future__ import annotations

import os
import sqlite3


class AtrinDatabase:
    """SQLite persistence with per-connection safety pragmas and forward migrations."""

    CURRENT_SCHEMA_VERSION = 2

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
    def _add_column_if_missing(
        cls, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        if column not in cls._columns(conn, table):
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_ledger (
                idempotency_key TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                expires_at TIMESTAMP,
                claim_owner TEXT,
                attempt INTEGER NOT NULL DEFAULT 0
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
                status TEXT NOT NULL DEFAULT 'PENDING',
                result TEXT,
                evidence TEXT,
                order_index INTEGER NOT NULL,
                provider_profile_id TEXT,
                fencing_token INTEGER,
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
                is_active BOOLEAN NOT NULL DEFAULT 1,
                installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        # Existing databases from v1 are upgraded in place. SQLite's
        # CREATE TABLE IF NOT EXISTS does not add new columns, so each
        # additive change must be explicit.
        self._add_column_if_missing(conn, "idempotency_ledger", "claim_owner", "TEXT")
        self._add_column_if_missing(
            conn, "idempotency_ledger", "attempt", "INTEGER NOT NULL DEFAULT 0"
        )
        self._add_column_if_missing(conn, "steps", "provider_profile_id", "TEXT")
        self._add_column_if_missing(conn, "steps", "fencing_token", "INTEGER")
        self._add_column_if_missing(
            conn, "workflow_checkpoints", "revision", "INTEGER NOT NULL DEFAULT 0"
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_workflow_step "
            "ON idempotency_ledger(workflow_id, step_id, provider_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_expiry "
            "ON idempotency_ledger(status, expires_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_steps_workflow_order "
            "ON steps(task_id, order_index)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_owner_expiry "
            "ON sessions(lock_owner, lease_expiry)"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO schema_metadata(key, value) VALUES ('schema_version', ?)
             ON CONFLICT(key) DO UPDATE SET value=excluded.value",
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
