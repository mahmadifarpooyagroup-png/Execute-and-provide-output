import os
import tempfile
from atrin_core.database import AtrinDatabase
from atrin_core.session_manager import SessionManager
from atrin_core.profile_paths import get_browser_profile_path
from atrin_core.models import AuthState

def test_create_and_lock_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = AtrinDatabase(db_path)
        manager = SessionManager(db)
        
        profile_id = "prof-1"
        manager.create_profile(profile_id, "prov-1", "acc-1", "Test Profile")
        
        token1 = manager.acquire_lock(profile_id, "workflow-1")
        assert token1 == 1
        
        token2 = manager.acquire_lock(profile_id, "workflow-2")
        assert token2 == 2

def test_profile_path_generation():
    path = get_browser_profile_path("provider-a", "profile-1")
    assert "provider-a_profile-1" in path
    assert "Atrin" in path
