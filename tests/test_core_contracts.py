import os
import tempfile

from atrin_core.database import AtrinDatabase
from atrin_core.models import AuthState, WorkflowState
from atrin_core.state_machine import (
    assert_workflow_transition,
    can_transition_workflow,
    transition_state,
)


def test_auth_state_machine_transition():
    assert transition_state(AuthState.UNKNOWN, "provider_registered") == AuthState.NOT_AUTHENTICATED
    try:
        transition_state(AuthState.ACTIVE, "invalid_event")
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass


def test_workflow_state_machine_has_terminal_states():
    assert can_transition_workflow(WorkflowState.WAITING_FOR_PROVIDER, WorkflowState.RECOVERING)
    assert can_transition_workflow(WorkflowState.CANCELLING, WorkflowState.CANCELLED)
    assert not can_transition_workflow(WorkflowState.CANCELLED, WorkflowState.EXECUTING)
    assert not can_transition_workflow(WorkflowState.COMPLETED, WorkflowState.EXECUTING)
    assert_workflow_transition(WorkflowState.RECOVERING, WorkflowState.EXECUTING)
    try:
        assert_workflow_transition(WorkflowState.CANCELLED, WorkflowState.RECOVERING)
        raise AssertionError("Terminal workflows must not transition")
    except ValueError:
        pass


def test_database_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "atrin_test.db")
        db = AtrinDatabase(db_path)
        conn = db.get_connection()
        result = conn.execute("PRAGMA journal_mode;").fetchone()
        assert result[0].lower() == "wal"
        tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        assert "idempotency_ledger" in tables
        assert "audit_log" in tables
        conn.close()
