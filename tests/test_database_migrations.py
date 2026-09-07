import sqlite3

from atrin_core.database import AtrinDatabase


def test_legacy_database_is_upgraded_in_place(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE idempotency_ledger (
            idempotency_key TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TIMESTAMP,
            expires_at TIMESTAMP
        );
        CREATE TABLE workflows (
            workflow_id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            state TEXT NOT NULL,
            plan_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            order_index INTEGER NOT NULL
        );
        CREATE TABLE steps (
            step_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            action TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            result TEXT,
            evidence TEXT,
            order_index INTEGER NOT NULL
        );
        CREATE TABLE workflow_checkpoints (
            workflow_id TEXT PRIMARY KEY,
            checkpoint_version INTEGER NOT NULL,
            payload TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()

    database = AtrinDatabase(str(db_path))
    connection = database.get_connection()
    try:
        assert "claim_owner" in {
            row["name"] for row in connection.execute("PRAGMA table_info(idempotency_ledger)")
        }
        assert "attempt" in {
            row["name"] for row in connection.execute("PRAGMA table_info(idempotency_ledger)")
        }
        assert "provider_profile_id" in {
            row["name"] for row in connection.execute("PRAGMA table_info(steps)")
        }
        assert "fencing_token" in {
            row["name"] for row in connection.execute("PRAGMA table_info(steps)")
        }
        assert "revision" in {
            row["name"] for row in connection.execute("PRAGMA table_info(workflow_checkpoints)")
        }
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()[0] == "2"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()
