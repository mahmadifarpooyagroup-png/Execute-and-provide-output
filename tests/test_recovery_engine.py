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

    async def verify_action(self, idempotency_key, *, operation_id=None):
        self.keys.append((idempotency_key, operation_id))
        return self.status


def make_store(temporary_directory, workflow_id):
    database = AtrinDatabase(os.path.join(temporary_directory, "test.db"))
    connection = database.get_connection()
    try:
        connection.execute(
            "INSERT INTO workflows(workflow_id, goal, state) VALUES (?, ?, ?)",
            (workflow_id, "recovery test", "RECOVERING"),
        )
        connection.commit()
    finally:
        connection.close()
    return database, SQLiteCheckpointStore(database)


def test_pause_handlers_persist_distinct_waiting_states():
    with tempfile.TemporaryDirectory() as temporary_directory:
        database, store = make_store(temporary_directory, "wf-1")
        _, store_2 = make_store(temporary_directory, "wf-2")
        controller = MockController()
        engine = RecoveryEngine(store, controller)
        checkpoint = {"step_id": "step-1", "checkpoint_version": 1}

        asyncio.run(engine.handle_network_unavailable("wf-1", checkpoint))
        engine2 = RecoveryEngine(store_2, controller)
        asyncio.run(engine2.handle_auth_required("wf-2", checkpoint))

        assert asyncio.run(store.load("wf-1"))["state"] == "WAITING_FOR_NETWORK"
        assert asyncio.run(store_2.load("wf-2"))["state"] == "WAITING_FOR_AUTH"
        assert [event[0] for event in controller.events] == ["pause", "pause"]


def test_resume_confirmed_action_requests_skip_from_generic_controller():
    with tempfile.TemporaryDirectory() as temporary_directory:
        database, store = make_store(temporary_directory, "wf-1")
        controller = MockController()
        verifier = MockVerifier("CONFIRMED")
        engine = RecoveryEngine(store, controller, verifier)
        connection = database.get_connection()
        try:
            connection.execute(
                "INSERT INTO tasks(task_id,workflow_id,description,status,order_index) VALUES (?,?,?,?,?)",
                ("task-1", "wf-1", "recovery task", "RUNNING", 0),
            )
            connection.execute(
                "INSERT INTO steps(step_id,task_id,action,provider_id,idempotency_key,operation_id,status,order_index) VALUES (?,?,?,?,?,?,?,?)",
                ("step-1", "task-1", "action", "provider-1", "action-1", "operation-1", "EXECUTING", 0),
            )
            connection.execute(
                "INSERT INTO idempotency_ledger(idempotency_key,workflow_id,step_id,provider_id,operation_id,status,confirmed_at) VALUES (?,?,?,?,?,'CONFIRMED',CURRENT_TIMESTAMP)",
                ("action-1", "wf-1", "step-1", "provider-1", "operation-1"),
            )
            connection.commit()
        finally:
            connection.close()

        asyncio.run(store.save("wf-1", {
            "action_idempotency_key": "action-1",
            "operation_id": "operation-1",
            "step_id": "step-1",
            "checkpoint_version": 1,
        }))
        result = asyncio.run(engine.resume_from_checkpoint("wf-1"))

        assert result.skipped_action is True
        assert controller.events == []
        assert verifier.keys == [("action-1", "operation-1")]
        connection = database.get_connection()
        try:
            assert connection.execute("SELECT status FROM steps WHERE step_id='step-1'").fetchone()[0] == "CONFIRMED"
            assert connection.execute("SELECT state FROM workflows WHERE workflow_id='wf-1'").fetchone()[0] == "COMPLETED"
        finally:
            connection.close()


def test_resume_pauses_when_action_state_is_ambiguous():
    with tempfile.TemporaryDirectory() as temporary_directory:
        _, store = make_store(temporary_directory, "wf-1")
        controller = MockController()
        engine = RecoveryEngine(store, controller, MockVerifier("IN_PROGRESS"))
        asyncio.run(store.save("wf-1", {"action_idempotency_key": "action-1", "operation_id": "op-1"}))

        result = asyncio.run(engine.resume_from_checkpoint("wf-1"))

        assert result.resumed is False
        assert controller.events == [("pause", "wf-1", "WAITING_FOR_PROVIDER")]
        assert asyncio.run(store.load("wf-1"))["state"] == "WAITING_FOR_PROVIDER"
