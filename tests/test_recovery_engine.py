import asyncio
import os
import tempfile

from atrin_core.database import AtrinDatabase
from atrin_core.recovery_engine import RecoveryEngine, SQLiteCheckpointStore


class MockController:
    def __init__(self):
        self.events = []

    async def pause_workflow(self, workflow_id, state):
        self.events.append(("pause", workflow_id, state))

    async def resume_workflow(self, workflow_id, checkpoint, skip_action=False):
        self.events.append(("resume", workflow_id, skip_action, checkpoint))


class MockVerifier:
    def __init__(self, status):
        self.status = status
        self.keys = []

    async def verify_action(self, idempotency_key):
        self.keys.append(idempotency_key)
        return self.status


def test_pause_handlers_persist_distinct_waiting_states():
    with tempfile.TemporaryDirectory() as temporary_directory:
        store = SQLiteCheckpointStore(AtrinDatabase(os.path.join(temporary_directory, "test.db")))
        controller = MockController()
        engine = RecoveryEngine(store, controller)
        checkpoint = {"step_id": "step-1", "checkpoint_version": 1}

        asyncio.run(engine.handle_network_unavailable("wf-1", checkpoint))
        asyncio.run(engine.handle_auth_required("wf-2", checkpoint))

        assert asyncio.run(store.load("wf-1"))["state"] == "WAITING_FOR_NETWORK"
        assert asyncio.run(store.load("wf-2"))["state"] == "WAITING_FOR_AUTH"
        assert [event[0] for event in controller.events] == ["pause", "pause"]


def test_resume_skips_confirmed_side_effect():
    with tempfile.TemporaryDirectory() as temporary_directory:
        store = SQLiteCheckpointStore(AtrinDatabase(os.path.join(temporary_directory, "test.db")))
        controller = MockController()
        verifier = MockVerifier("CONFIRMED")
        engine = RecoveryEngine(store, controller, verifier)
        asyncio.run(store.save("wf-1", {"action_idempotency_key": "action-1", "step_id": "step-1"}))

        result = asyncio.run(engine.resume_from_checkpoint("wf-1"))

        assert result.skipped_action is True
        assert controller.events[0][2] is True
        assert verifier.keys == ["action-1"]


def test_resume_does_not_dispatch_while_action_is_in_progress():
    with tempfile.TemporaryDirectory() as temporary_directory:
        store = SQLiteCheckpointStore(AtrinDatabase(os.path.join(temporary_directory, "test.db")))
        controller = MockController()
        engine = RecoveryEngine(store, controller, MockVerifier("IN_PROGRESS"))
        asyncio.run(store.save("wf-1", {"action_idempotency_key": "action-1"}))

        result = asyncio.run(engine.resume_from_checkpoint("wf-1"))

        assert result.resumed is False
        assert controller.events == []