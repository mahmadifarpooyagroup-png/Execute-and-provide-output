import os
import tempfile
import pytest
from atrin_core.database import AtrinDatabase
from atrin_core.session_manager import SessionManager
from atrin_core.profile_paths import get_browser_profile_path


@pytest.fixture
def db_session():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    db = AtrinDatabase(db_path)
    yield db
    
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
    # Remove WAL files if they exist
    for suffix in ["-wal", "-shm"]:
        wal_path = db_path + suffix
        if os.path.exists(wal_path):
            os.remove(wal_path)


def test_create_profile_and_path(db_session):
    """Test creating a profile and verifying the browser profile path."""
    manager = SessionManager(db_session)
    
    # Create a profile
    profile_id = manager.create_profile(
        provider_id="test_provider",
        account_id="test_account",
        name="Test Profile"
    )
    
    assert profile_id is not None
    assert profile_id > 0
    
    # Verify browser profile path generation
    path = get_browser_profile_path("test_provider", str(profile_id))
    assert path is not None
    assert "test_provider_" + str(profile_id) in path
    assert os.path.isdir(path)
    
    # Verify path is NOT inside git repository (Section 17)
    import subprocess
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        # Path should not be inside the git repo
        assert not path.startswith(git_root), f"Profile path {path} should not be inside git repo {git_root}"
    except subprocess.CalledProcessError:
        # Not in a git repo, skip this check
        pass


def test_acquire_lock_increments_fencing_token(db_session):
    """Test that acquire_lock increments fencing_token by exactly 1 each time."""
    manager = SessionManager(db_session)
    
    # Create a profile
    profile_id = manager.create_profile(
        provider_id="test_provider",
        account_id="test_account",
        name="Test Profile"
    )
    
    # First lock acquisition - should increment from 0 to 1
    token1 = manager.acquire_lock(profile_id, "workflow_1")
    assert token1 == 1
    
    # Second lock acquisition - should increment from 1 to 2
    token2 = manager.acquire_lock(profile_id, "workflow_2")
    assert token2 == 2
    
    # Third lock acquisition - should increment from 2 to 3
    token3 = manager.acquire_lock(profile_id, "workflow_3")
    assert token3 == 3
    
    # Verify the fencing_token in the database
    conn = db_session.get_connection()
    row = conn.execute(
        "SELECT fencing_token FROM provider_profiles WHERE id = ?",
        (profile_id,)
    ).fetchone()
    conn.close()
    
    assert row[0] == 3, f"Expected fencing_token to be 3, got {row[0]}"


def test_release_lock_clears_ownership(db_session):
    """Test that release_lock clears the lock_owner."""
    manager = SessionManager(db_session)
    
    # Create a profile and acquire lock
    profile_id = manager.create_profile(
        provider_id="test_provider",
        account_id="test_account",
        name="Test Profile"
    )
    
    manager.acquire_lock(profile_id, "workflow_1")
    
    # Verify lock is held
    conn = db_session.get_connection()
    row = conn.execute(
        "SELECT lock_owner, state FROM sessions WHERE provider_profile_id = ?",
        (profile_id,)
    ).fetchone()
    assert row[0] == "workflow_1"
    assert row[1] == "ACTIVE"
    
    # Release the lock
    session_id = f"workflow_1_{profile_id}"
    manager.release_lock(session_id)
    
    # Verify lock is released
    row = conn.execute(
        "SELECT lock_owner, state FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    conn.close()
    
    assert row[0] is None, f"Expected lock_owner to be NULL, got {row[0]}"
    assert row[1] == "IDLE", f"Expected state to be IDLE, got {row[1]}"


def test_get_session_state_returns_correct_state(db_session):
    """Test that get_session_state returns the correct session state."""
    manager = SessionManager(db_session)
    
    # Create a profile
    profile_id = manager.create_profile(
        provider_id="test_provider",
        account_id="test_account",
        name="Test Profile"
    )
    
    # Initially, no session exists
    state = manager.get_session_state(profile_id)
    assert state is None
    
    # Acquire lock - should create session with ACTIVE state
    manager.acquire_lock(profile_id, "workflow_1")
    state = manager.get_session_state(profile_id)
    assert state == "ACTIVE"
    
    # Release lock - should change state to IDLE
    session_id = f"workflow_1_{profile_id}"
    manager.release_lock(session_id)
    state = manager.get_session_state(profile_id)
    assert state == "IDLE"
