import os
import tempfile
from atrin_core.models import AuthState
from atrin_core.state_machine import transition_state
from atrin_core.database import AtrinDatabase

def test_state_machine_transition():
    assert transition_state(AuthState.UNKNOWN, "provider_registered") == AuthState.NOT_AUTHENTICATED
    try:
        transition_state(AuthState.ACTIVE, "invalid_event")
        assert False, "Should have raised ValueError"
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
