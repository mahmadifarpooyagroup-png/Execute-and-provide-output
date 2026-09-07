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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        CREATE TABLE plugins_registry (
            plugin_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()

    database = AtrinDatabase(str(db_path))
    connection = database.get_connection()
    try:
        ledger_columns = {row["name"] for row in connection.execute("PRAGMA table_info(idempotency_ledger)")}
        step_columns = {row["name"] for row in connection.execute("PRAGMA table_info(steps)")}
        workflow_columns = {row["name"] for row in connection.execute("PRAGMA table_info(workflows)")}
        checkpoint_columns = {row["name"] for row in connection.execute("PRAGMA table_info(workflow_checkpoints)")}
        plugin_columns = {row["name"] for row in connection.execute("PRAGMA table_info(plugins_registry)")}
        assert {"claim_owner", "attempt", "operation_id", "confirmed_at", "expires_at"}.issubset(ledger_columns)
        assert {"provider_profile_id", "fencing_token", "operation_id", "side_effecting"}.issubset(step_columns)
        assert "client_request_id" in workflow_columns
        assert "revision" in checkpoint_columns
        assert {"path", "sha256", "updated_at"}.issubset(plugin_columns)
        assert connection.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()[0] == "6"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_operation_ids_are_backfilled_and_unique(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
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
        CREATE TABLE idempotency_ledger (
            idempotency_key TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            status TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO workflows(workflow_id,goal,state) VALUES ('w1','goal','IDLE')")
    conn.execute("INSERT INTO tasks(task_id,workflow_id,description,order_index) VALUES ('t1','w1','task',0)")
    conn.execute("INSERT INTO steps(step_id,task_id,action,provider_id,idempotency_key,order_index) VALUES ('s1','t1','a','p','k1',0)")
    conn.execute("INSERT INTO idempotency_ledger(idempotency_key,workflow_id,step_id,provider_id,status) VALUES ('k1','w1','s1','p','PENDING')")
    conn.commit()
    conn.close()

    database = AtrinDatabase(str(db_path))
    connection = database.get_connection()
    try:
        operation_id = connection.execute("SELECT operation_id FROM steps WHERE step_id='s1'").fetchone()[0]
        ledger_operation = connection.execute("SELECT operation_id FROM idempotency_ledger WHERE idempotency_key='k1'").fetchone()[0]
        assert operation_id
        assert operation_id == ledger_operation
        assert connection.execute("SELECT COUNT(*) FROM steps WHERE operation_id IS NOT NULL").fetchone()[0] == 1
    finally:
        connection.close()
