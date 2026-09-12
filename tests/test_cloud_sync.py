import pytest

from atrin_core.cloud_sync import CloudSyncManager
from atrin_core.database import AtrinDatabase


class FakeCheckpointStore:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint

    async def load(self, workflow_id):
        return self.checkpoint


class FakeRecoveryEngine:
    def __init__(self, checkpoint):
        self.checkpoint_store = FakeCheckpointStore(checkpoint)


class FakeStorage:
    def __init__(self):
        self.objects = {}

    async def upload(self, remote_id, payload):
        self.objects[remote_id] = payload

    async def download(self, remote_id):
        return self.objects[remote_id]


def create_workflow_parent(database: AtrinDatabase, workflow_id: str = "workflow-1"):
    connection = database.get_connection()
    try:
        connection.execute(
            "INSERT INTO workflows(workflow_id, goal, state) VALUES (?, ?, ?)",
            (workflow_id, "sync test", "IDLE"),
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def manager(tmp_path):
    checkpoint = {
        "workflow_id": "workflow-1",
        "state": "EXECUTING",
        "updated_at": "2026-09-04T10:00:00+00:00",
        "checkpoint_version": 2,
    }
    storage = FakeStorage()
    database = AtrinDatabase(str(tmp_path / "atrin.db"))
    create_workflow_parent(database)
    manager = CloudSyncManager(FakeRecoveryEngine(checkpoint), database, storage)
    manager.configure_provider("local_network", {"path": str(tmp_path / "remote"), "encryption_key": "user secret!"})
    manager.storage_provider = storage
    return manager, storage


def test_encryption_roundtrip(manager):
    cloud_sync, _ = manager
    payload = {"state": "EXECUTING", "items": [1, 2, 3]}
    encrypted = cloud_sync.encrypt_payload(payload)
    assert encrypted != str(payload).encode()
    assert cloud_sync.decrypt_payload(encrypted) == payload


def test_key_fingerprint_does_not_equal_passphrase_hash(manager):
    cloud_sync, _ = manager
    assert cloud_sync.sync_config is not None
    assert cloud_sync.sync_config.encryption_key_hash != __import__("hashlib").sha256(b"user secret!").hexdigest()
    assert len(cloud_sync.sync_config.encryption_key_hash) == 64


@pytest.mark.asyncio
async def test_push_and_pull_checkpoint(manager):
    cloud_sync, storage = manager
    status = await cloud_sync.push_checkpoint("workflow-1")
    checkpoint = await cloud_sync.pull_checkpoint("workflow-1")
    assert status.sync_direction == "PUSH"
    assert checkpoint["workflow_id"] == "workflow-1"
    assert len(storage.objects) == 1


@pytest.mark.asyncio
async def test_pull_reports_remote_conflict(tmp_path):
    local = {"workflow_id": "workflow-1", "revision": 1, "updated_at": "2026-09-04T10:00:00+00:00"}
    remote = {"workflow_id": "workflow-1", "revision": 2, "updated_at": "2026-09-04T11:00:00+00:00"}
    storage = FakeStorage()
    database = AtrinDatabase(str(tmp_path / "atrin.db"))
    create_workflow_parent(database)
    manager = CloudSyncManager(FakeRecoveryEngine(local), database, storage)
    manager.configure_provider("webdav", {"endpoint_url": "https://sync.example.test/dav", "encryption_key": "user secret!"})
    manager.storage_provider = storage
    storage.objects["checkpoints/workflow-1.checkpoint"] = manager.encrypt_payload({
        "checkpoint": remote,
        "synced_at": remote["updated_at"],
        "revision": 2,
        "content_hash": manager._content_hash(remote),
        "format_version": 1,
    })

    result = await manager.pull_checkpoint("workflow-1")
    assert result["conflict"] is True
    assert result["local_revision"] == 1
    assert result["remote_revision"] == 2
    assert result["local_timestamp"] == local["updated_at"]
    assert result["remote_timestamp"] == remote["updated_at"]
    connection = manager.database.get_connection()
    try:
        row = connection.execute(
            "SELECT sync_status, conflict_flag FROM sync_metadata WHERE workflow_id=?", ("workflow-1",)
        ).fetchone()
        assert row["sync_status"] == "CONFLICT"
        assert row["conflict_flag"] == 1
    finally:
        connection.close()


# ── FIX (بند ۹/۲۱): compare-and-swap conflict detection on push ────────────

@pytest.mark.asyncio
async def test_first_push_succeeds_with_no_prior_remote(manager):
    """No remote object exists yet — push must succeed without a conflict check false-positive."""
    cloud_sync, storage = manager
    status = await cloud_sync.push_checkpoint("workflow-1")
    assert status.sync_direction == "PUSH"
    assert len(storage.objects) == 1


@pytest.mark.asyncio
async def test_second_push_from_same_client_succeeds(manager):
    """
    A client pushing twice in a row (no other client interleaved) must
    succeed both times — its own last_known_remote_revision was updated
    by the first push.
    """
    cloud_sync, storage = manager
    await cloud_sync.push_checkpoint("workflow-1")

    # Bump the local checkpoint's revision to simulate normal progress
    cloud_sync.recovery_engine.checkpoint_store.checkpoint = {
        **cloud_sync.recovery_engine.checkpoint_store.checkpoint,
        "checkpoint_version": 3,
        "revision": 1,
    }
    status = await cloud_sync.push_checkpoint("workflow-1")
    assert status.sync_direction == "PUSH"


@pytest.mark.asyncio
async def test_push_rejects_overwrite_when_remote_advanced_concurrently(tmp_path):
    """
    Core CAS test: client A pushes (revision 1). Client B (a second
    CloudSyncManager instance sharing the same storage/database) pushes a
    NEWER revision (2) without client A knowing. When client A then tries to
    push again with its stale view, push_checkpoint() must raise
    RemoteRevisionConflictError instead of silently overwriting B's write.
    """
    from atrin_core.cloud_sync import CloudSyncManager, RemoteRevisionConflictError

    checkpoint_a = {"workflow_id": "workflow-1", "revision": 1, "updated_at": "2026-09-04T10:00:00+00:00"}
    storage = FakeStorage()
    database = AtrinDatabase(str(tmp_path / "atrin.db"))
    create_workflow_parent(database)

    client_a = CloudSyncManager(FakeRecoveryEngine(checkpoint_a), database, storage)
    client_a.configure_provider("local_network", {"path": str(tmp_path / "remote"), "encryption_key": "shared secret!"})
    client_a.storage_provider = storage

    # Client A's first push succeeds and records last_known_remote_revision=1
    await client_a.push_checkpoint("workflow-1")

    # Client B pushes revision 2 directly to shared storage, simulating a
    # concurrent writer client A has no knowledge of.
    checkpoint_b = {"workflow_id": "workflow-1", "revision": 2, "updated_at": "2026-09-04T11:00:00+00:00"}
    database_b = AtrinDatabase(str(tmp_path / "atrin-b.db"))
    create_workflow_parent(database_b)
    client_b = CloudSyncManager(FakeRecoveryEngine(checkpoint_b), database_b, storage)
    client_b.configure_provider("local_network", {"path": str(tmp_path / "remote"), "encryption_key": "shared secret!"})
    client_b.storage_provider = storage
    await client_b.push_checkpoint("workflow-1")  # client B has no prior metadata → first push succeeds

    # Client A still thinks the remote is at revision 1 (its own last push).
    # If it now tries to push its own revision-1 checkpoint again, it must
    # be refused because the remote has actually moved to revision 2.
    with pytest.raises(RemoteRevisionConflictError) as exc_info:
        await client_a.push_checkpoint("workflow-1")
    assert exc_info.value.remote_revision == 2
    assert exc_info.value.workflow_id == "workflow-1"


@pytest.mark.asyncio
async def test_push_force_bypasses_conflict_check(tmp_path):
    """force=True must allow an intentional overwrite after manual conflict resolution."""
    from atrin_core.cloud_sync import CloudSyncManager, RemoteRevisionConflictError

    checkpoint_a = {"workflow_id": "workflow-1", "revision": 1, "updated_at": "2026-09-04T10:00:00+00:00"}
    storage = FakeStorage()
    database = AtrinDatabase(str(tmp_path / "atrin.db"))
    create_workflow_parent(database)

    client_a = CloudSyncManager(FakeRecoveryEngine(checkpoint_a), database, storage)
    client_a.configure_provider("local_network", {"path": str(tmp_path / "remote"), "encryption_key": "shared secret!"})
    client_a.storage_provider = storage
    await client_a.push_checkpoint("workflow-1")

    checkpoint_b = {"workflow_id": "workflow-1", "revision": 2, "updated_at": "2026-09-04T11:00:00+00:00"}
    database_b = AtrinDatabase(str(tmp_path / "atrin-b.db"))
    create_workflow_parent(database_b)
    client_b = CloudSyncManager(FakeRecoveryEngine(checkpoint_b), database_b, storage)
    client_b.configure_provider("local_network", {"path": str(tmp_path / "remote"), "encryption_key": "shared secret!"})
    client_b.storage_provider = storage
    await client_b.push_checkpoint("workflow-1")

    # Without force: conflict
    with pytest.raises(RemoteRevisionConflictError):
        await client_a.push_checkpoint("workflow-1")

    # With force=True: overwrite proceeds
    status = await client_a.push_checkpoint("workflow-1", force=True)
    assert status.sync_direction == "PUSH"


@pytest.mark.asyncio
async def test_pull_updates_last_known_remote_revision(manager):
    """After pull_checkpoint(), the client's baseline must reflect the pulled revision."""
    cloud_sync, storage = manager
    await cloud_sync.push_checkpoint("workflow-1")
    await cloud_sync.pull_checkpoint("workflow-1")

    last_known = cloud_sync._read_last_known_remote_revision("workflow-1")
    assert last_known is not None
