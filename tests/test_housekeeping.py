"""
Tests for database housekeeping (بند ۲/۱۵ — retentionDays real consumer).
"""
import os
import tempfile

from fastapi.testclient import TestClient

from atrin_core.database import AtrinDatabase
from atrin_core.runtime import create_app
from atrin_core.security import LocalSecurityManager


def _make_db(tmpdir: str) -> AtrinDatabase:
    return AtrinDatabase(os.path.join(tmpdir, "test.db"))


def _insert_workflow(db: AtrinDatabase, workflow_id: str, state: str, updated_at: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO workflows (workflow_id, goal, state, updated_at) VALUES (?, ?, ?, ?)",
            (workflow_id, "test goal", state, updated_at),
        )
        conn.execute(
            "INSERT INTO tasks (task_id, workflow_id, description, status, order_index) VALUES (?, ?, ?, ?, ?)",
            (f"{workflow_id}-task", workflow_id, "task", "COMPLETED", 0),
        )
        conn.execute(
            "INSERT INTO steps (step_id, task_id, action, provider_id, idempotency_key, status, order_index) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"{workflow_id}-step", f"{workflow_id}-task", "noop", "prov-1", f"key-{workflow_id}", "CONFIRMED", 0),
        )
        conn.execute(
            "INSERT INTO audit_log (workflow_id, event_type, actor, payload, prev_hash, entry_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (workflow_id, "WORKFLOW_CREATED", "test", "{}", "0" * 64, "1" * 64),
        )
        conn.commit()
    finally:
        conn.close()


def test_purge_deletes_old_terminal_workflows():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        _insert_workflow(db, "wf-old", "COMPLETED", "2020-01-01 00:00:00")
        _insert_workflow(db, "wf-new", "COMPLETED", "2099-01-01 00:00:00")

        deleted = db.purge_workflows_older_than(retention_days=30)
        assert deleted == 1

        conn = db.get_connection()
        try:
            remaining = {row["workflow_id"] for row in conn.execute("SELECT workflow_id FROM workflows").fetchall()}
        finally:
            conn.close()
        assert remaining == {"wf-new"}


def test_purge_does_not_touch_active_workflows():
    """A non-terminal workflow (EXECUTING) must never be purged, regardless of age."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        _insert_workflow(db, "wf-active-old", "EXECUTING", "2020-01-01 00:00:00")

        deleted = db.purge_workflows_older_than(retention_days=30)
        assert deleted == 0

        conn = db.get_connection()
        try:
            row = conn.execute("SELECT workflow_id FROM workflows WHERE workflow_id=?", ("wf-active-old",)).fetchone()
        finally:
            conn.close()
        assert row is not None


def test_purge_deletes_dependent_rows_fk_safe():
    """Deleting a stale workflow must also remove its tasks/steps/audit — no orphans, no FK errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        _insert_workflow(db, "wf-cascade", "CANCELLED", "2020-01-01 00:00:00")

        deleted = db.purge_workflows_older_than(retention_days=1)
        assert deleted == 1

        conn = db.get_connection()
        try:
            assert conn.execute("SELECT COUNT(*) AS n FROM tasks WHERE workflow_id='wf-cascade'").fetchone()["n"] == 0
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM steps WHERE task_id='wf-cascade-task'"
            ).fetchone()["n"] == 0
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM audit_log WHERE workflow_id='wf-cascade'"
            ).fetchone()["n"] == 0
        finally:
            conn.close()


def test_purge_rejects_invalid_retention_days():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        raised = False
        try:
            db.purge_workflows_older_than(retention_days=0)
        except ValueError:
            raised = True
        assert raised, "expected ValueError for retention_days=0"


def test_housekeeping_endpoint_round_trip(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    token_path = str(tmp_path / "runtime.token")
    app = create_app(db_path=db_path, token_path=token_path)
    security = LocalSecurityManager(token_file_path=token_path)
    token = security.get_or_create_token()
    client = TestClient(app)
    headers = {"X-Atrin-Token": token}

    db = AtrinDatabase(db_path)
    _insert_workflow(db, "wf-http-old", "FAILED", "2020-01-01 00:00:00")

    response = client.post("/api/v1/housekeeping/run?retention_days=30", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["retention_days"] == 30
    assert body["workflows_deleted"] == 1


def test_housekeeping_endpoint_requires_auth(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    token_path = str(tmp_path / "runtime.token")
    app = create_app(db_path=db_path, token_path=token_path)
    client = TestClient(app)
    response = client.post("/api/v1/housekeeping/run?retention_days=30")
    assert response.status_code == 401


def test_housekeeping_endpoint_rejects_invalid_retention(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    token_path = str(tmp_path / "runtime.token")
    app = create_app(db_path=db_path, token_path=token_path)
    security = LocalSecurityManager(token_file_path=token_path)
    token = security.get_or_create_token()
    client = TestClient(app)
    headers = {"X-Atrin-Token": token}
    response = client.post("/api/v1/housekeeping/run?retention_days=0", headers=headers)
    assert response.status_code == 422
