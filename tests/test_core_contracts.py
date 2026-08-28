"""Tests for core contracts per Phase 1 specification."""

import pytest
import os
import tempfile
from atrin_core.models import AuthState, ConnectionKind, Provider, ProviderProfile, Session, IdempotencyRecord
from atrin_core.database import AtrinDatabase
from atrin_core.state_machine import transition_state, STATE_TRANSITIONS


class TestStateMachine:
    """Test state machine transitions per Section 13.1."""
    
    def test_unknown_to_not_authenticated(self):
        """Test transition from UNKNOWN to NOT_AUTHENTICATED on provider_registered."""
        current_state = AuthState.UNKNOWN
        event = "provider_registered"
        
        new_state = transition_state(current_state, event)
        
        assert new_state == AuthState.NOT_AUTHENTICATED
    
    def test_invalid_transition_raises_valueerror(self):
        """Test that invalid transitions raise ValueError."""
        with pytest.raises(ValueError, match="Invalid state transition"):
            transition_state(AuthState.UNKNOWN, "invalid_event")


class TestDatabase:
    """Test database initialization per Section 48 and tables per Sections 35.1, 42.1."""
    
    def test_database_initializes_with_wal_mode(self):
        """Test that database initializes with WAL journal mode."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        
        try:
            db = AtrinDatabase(db_path)
            
            # Verify WAL mode is enabled per Section 48
            journal_mode = db.check_journal_mode()
            assert journal_mode.lower() == "wal", f"Expected WAL mode, got {journal_mode}"
            
            db.close()
        finally:
            # Cleanup
            if os.path.exists(db_path):
                os.remove(db_path)
            # WAL files may also exist
            for suffix in ["-wal", "-shm"]:
                wal_path = db_path + suffix
                if os.path.exists(wal_path):
                    os.remove(wal_path)
    
    def test_idempotency_ledger_table_exists(self):
        """Test that idempotency_ledger table is created per Section 35.1."""
        db = AtrinDatabase(":memory:")
        
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='idempotency_ledger'
        """)
        result = cursor.fetchone()
        
        assert result is not None, "idempotency_ledger table should exist"
        db.close()
    
    def test_audit_log_table_exists(self):
        """Test that audit_log table with hash chain fields exists per Section 42.1."""
        db = AtrinDatabase(":memory:")
        
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA table_info(audit_log)")
        columns = {row[1] for row in cursor.fetchall()}
        
        # Verify required columns including prev_hash and entry_hash
        assert "prev_hash" in columns, "audit_log should have prev_hash column"
        assert "entry_hash" in columns, "audit_log should have entry_hash column"
        
        db.close()
    
    def test_audit_log_hash_chain(self):
        """Test that audit log entries form a valid hash chain."""
        db = AtrinDatabase(":memory:")
        
        # Insert first entry
        seq1 = db.append_audit_log(
            workflow_id="wf-001",
            event_type="test_event",
            actor="system",
            payload={"action": "first"}
        )
        
        # Insert second entry
        seq2 = db.append_audit_log(
            workflow_id="wf-001",
            event_type="test_event",
            actor="system",
            payload={"action": "second"}
        )
        
        # Verify entries exist and chain properly
        cursor = db.conn.cursor()
        cursor.execute("SELECT seq, prev_hash, entry_hash FROM audit_log ORDER BY seq")
        rows = cursor.fetchall()
        
        assert len(rows) == 2
        # First entry should have NULL prev_hash
        assert rows[0][1] is None
        # Second entry's prev_hash should equal first entry's entry_hash
        assert rows[1][1] == rows[0][2]
        
        db.close()


class TestModels:
    """Test Pydantic models."""
    
    def test_provider_profile_has_fencing_token(self):
        """Test that ProviderProfile includes fencing_token per Section 20.1."""
        profile = ProviderProfile(
            id="profile-001",
            provider_id="provider-001"
        )
        
        assert hasattr(profile, 'fencing_token')
        assert profile.fencing_token == 0
    
    def test_connection_kind_enum(self):
        """Test ConnectionKind enum values."""
        assert ConnectionKind.WEB.value == "web"
        assert ConnectionKind.DESKTOP.value == "desktop"
        assert ConnectionKind.API.value == "api"
    
    def test_auth_state_enum(self):
        """Test AuthState enum values per Section 13.1."""
        assert AuthState.UNKNOWN.value == "UNKNOWN"
        assert AuthState.NOT_AUTHENTICATED.value == "NOT_AUTHENTICATED"
        assert AuthState.ACTIVE.value == "ACTIVE"
    
    def test_session_model(self):
        """Test Session model creation."""
        session = Session(
            session_id="session-001",
            provider_profile_id="profile-001"
        )
        
        assert session.session_id == "session-001"
        assert session.state == AuthState.UNKNOWN
    
    def test_idempotency_record_model(self):
        """Test IdempotencyRecord model per Section 35.1."""
        record = IdempotencyRecord(
            idempotency_key="idem-001",
            workflow_id="wf-001",
            step_id="step-001",
            provider_id="provider-001",
            status="PENDING"
        )
        
        assert record.idempotency_key == "idem-001"
        assert record.status == "PENDING"
