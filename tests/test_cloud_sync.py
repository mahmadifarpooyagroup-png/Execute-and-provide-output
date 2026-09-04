from datetime import datetime, timezone

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


@pytest.fixture
def manager(tmp_path):
    checkpoint = {
        "workflow_id": "workflow-1",
        "state": "EXECUTING",
        "updated_at": "2026-09-04T10:00:00+00:00",
        "checkpoint_version": 2,
    }
    storage = FakeStorage()
    manager = CloudSyncManager(FakeRecoveryEngine(checkpoint), AtrinDatabase(str(tmp_path / "atrin.db")), storage)
    manager.configure_provider("local_network", {"path": str(tmp_path / "remote"), "encryption_key": "user secret"})
    manager.storage_provider = storage
    return manager, storage


def test_encryption_roundtrip(manager):
    cloud_sync, _ = manager
    payload = {"state": "EXECUTING", "items": [1, 2, 3]}

    encrypted = cloud_sync.encrypt_payload(payload)

    assert encrypted != str(payload).encode()
    assert cloud_sync.decrypt_payload(encrypted) == payload


@pytest.mark.asyncio
async def test_push_and_pull_checkpoint(manager):
    cloud_sync, storage = manager

    status = await cloud_sync.push_checkpoint("workflow-1")
    checkpoint = await cloud_sync.pull_checkpoint("workflow-1")

    assert status.sync_direction == "PUSH"
    assert checkpoint["workflow_id"] == "workflow-1"
    assert len(storage.objects) == 1


@pytest.mark.asyncio
async def test_pull_reports_newer_remote_conflict(tmp_path):
    local = {"workflow_id": "workflow-1", "updated_at": "2026-09-04T10:00:00+00:00"}
    remote = {"workflow_id": "workflow-1", "updated_at": "2026-09-04T11:00:00+00:00"}
    storage = FakeStorage()
    manager = CloudSyncManager(FakeRecoveryEngine(local), AtrinDatabase(str(tmp_path / "atrin.db")), storage)
    manager.configure_provider("webdav", {"endpoint_url": "https://sync.example.test/dav", "encryption_key": "user secret"})
    manager.storage_provider = storage
    storage.objects["checkpoints/workflow-1.checkpoint"] = manager.encrypt_payload({
        "checkpoint": remote,
        "synced_at": remote["updated_at"],
        "version": "1",
    })

    result = await manager.pull_checkpoint("workflow-1")

    assert result["conflict"] is True
    assert result["local_timestamp"] == local["updated_at"]
    assert result["remote_timestamp"] == remote["updated_at"]
    row = manager.database.get_connection().execute(
        "SELECT sync_status, conflict_flag FROM sync_metadata WHERE workflow_id = ?", ("workflow-1",)
    ).fetchone()
    assert row["sync_status"] == "CONFLICT"
    assert row["conflict_flag"] == 1
