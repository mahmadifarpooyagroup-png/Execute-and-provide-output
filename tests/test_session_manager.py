import os
import tempfile

import pytest

from atrin_core.database import AtrinDatabase
from atrin_core.models import AuthState
from atrin_core.profile_paths import get_browser_profile_path
from atrin_core.session_manager import SessionManager


def test_create_and_lock_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = AtrinDatabase(db_path)
        manager = SessionManager(db)
        profile_id = "prof-1"
        manager.create_profile(profile_id, "prov-1", "acc-1", "Test Profile")

        token1 = manager.acquire_lock(profile_id, "workflow-1")
        assert token1 == 1
        assert manager.validate_execution_lease(profile_id, "workflow-1", token1) is True

        token1_again = manager.acquire_lock(profile_id, "workflow-1")
        assert token1_again == token1

        with pytest.raises(RuntimeError, match="locked by workflow-1"):
            manager.acquire_lock(profile_id, "workflow-2")

        assert manager.renew_lock(profile_id, "workflow-1", token1) is True
        assert manager.release_lock(profile_id, "workflow-1", token1) is True
        assert manager.validate_execution_lease(profile_id, "workflow-1", token1) is False


def test_expired_owner_can_be_replaced_with_new_fencing_generation():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = AtrinDatabase(os.path.join(tmpdir, "test.db"))
        manager = SessionManager(db)
        profile_id = "prof-1"
        manager.create_profile(profile_id, "prov-1", "acc-1", "Test Profile")
        token1 = manager.acquire_lock(profile_id, "workflow-1")

        connection = db.get_connection()
        connection.execute(
            "UPDATE sessions SET lease_expiry=0 WHERE session_id=?", (profile_id,)
        )
        connection.commit()
        connection.close()

        token2 = manager.acquire_lock(profile_id, "workflow-2")
        assert token2 == token1 + 1
        assert manager.validate_execution_lease(profile_id, "workflow-1", token1) is False
        assert manager.validate_execution_lease(profile_id, "workflow-2", token2) is True


def test_fencing_token_is_exact_not_greater_or_less():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = AtrinDatabase(os.path.join(tmpdir, "test.db"))
        manager = SessionManager(db)
        profile_id = "prof-1"
        manager.create_profile(profile_id, "prov-1", "acc-1", "Test Profile")
        token = manager.acquire_lock(profile_id, "workflow-1")

        assert manager.validate_fencing_token(profile_id, token) is True
        assert manager.validate_fencing_token(profile_id, token - 1) is False
        assert manager.validate_fencing_token(profile_id, token + 1) is False


def test_profile_path_generation():
    path = get_browser_profile_path("provider-a", "profile-1")
    assert "provider-a_profile-1" in path
    assert "Atrin" in path
