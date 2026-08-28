import asyncio
import os
import tempfile

from atrin_core.database import AtrinDatabase
from atrin_core.models import Step, Task, WorkflowState
from atrin_core.workflow_engine import WorkflowEngine


class MockAdapter:
    def __init__(self, verification="NOT_STARTED"):
        self.verification = verification
        self.calls = []

    async def execute(self, action, idempotency_key):
        self.calls.append((action, idempotency_key))
        return {"result": "ok", "evidence": "receipt"}

    async def verify_action(self, idempotency_key):
        return self.verification


def build_engine(adapter=None):
    temporary_directory = tempfile.TemporaryDirectory()
    database = AtrinDatabase(os.path.join(temporary_directory.name, "workflow.db"))
    adapter = adapter or MockAdapter()
    engine = WorkflowEngine(database, {"provider-a": adapter})
    return temporary_directory, database, engine, adapter


def test_create_workflow_and_state():
    temporary_directory, database, engine, _ = build_engine()
    try:
        workflow_id = engine.create_workflow("ship feature", [
            Task(task_id="task-1", description="implement", steps=[
                Step(step_id="step-1", action="write", provider_id="provider-a")
            ])
        ])
        assert engine.get_workflow_state(workflow_id) == WorkflowState.IDLE
        connection = database.get_connection()
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 1
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_execute_step_writes_pending_and_confirmed_checkpoints_atomically():
    temporary_directory, database, engine, adapter = build_engine()
    try:
        workflow_id = engine.create_workflow("ship", [Task(task_id="task-1", description="do", steps=[
            Step(step_id="step-1", action="write", provider_id="provider-a", idempotency_key="key-1")
        ])])
        asyncio.run(engine.execute_step(workflow_id, "step-1"))
        assert adapter.calls == [("write", "key-1")]
        checkpoint = asyncio.run(engine.load(workflow_id))
        assert checkpoint["last_result"] == "ok"
        connection = database.get_connection()
        assert connection.execute("SELECT status FROM idempotency_ledger WHERE idempotency_key = 'key-1'").fetchone()[0] == "CONFIRMED"
        assert connection.execute("SELECT status FROM steps WHERE step_id = 'step-1'").fetchone()[0] == "CONFIRMED"
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_resume_confirmed_action_skips_execution():
    adapter = MockAdapter("CONFIRMED")
    temporary_directory, _, engine, _ = build_engine(adapter)
    try:
        workflow_id = engine.create_workflow("ship", [Task(task_id="task-1", description="do", steps=[
            Step(step_id="step-1", action="write", provider_id="provider-a", idempotency_key="key-1")
        ])])
        asyncio.run(engine.save(workflow_id, {"step_id": "step-1", "provider_id": "provider-a",
                                               "action_idempotency_key": "key-1", "state": "WAITING_FOR_NETWORK"}))
        result = asyncio.run(engine.resume_workflow(workflow_id))
        assert result.skipped_action is True
        assert adapter.calls == []
    finally:
        temporary_directory.cleanup()


def test_resume_failed_action_retries():
    adapter = MockAdapter("FAILED")
    temporary_directory, _, engine, _ = build_engine(adapter)
    try:
        workflow_id = engine.create_workflow("ship", [Task(task_id="task-1", description="do", steps=[
            Step(step_id="step-1", action="write", provider_id="provider-a", idempotency_key="key-1")
        ])])
        asyncio.run(engine.save(workflow_id, {"step_id": "step-1", "provider_id": "provider-a",
                                               "action_idempotency_key": "key-1", "state": "WAITING_FOR_NETWORK"}))
        asyncio.run(engine.resume_workflow(workflow_id))
        assert adapter.calls == [("write", "key-1")]
    finally:
        temporary_directory.cleanup()


def test_pause_and_resume_cycle():
    temporary_directory, _, engine, adapter = build_engine()
    try:
        workflow_id = engine.create_workflow("ship", [Task(task_id="task-1", description="do", steps=[
            Step(step_id="step-1", action="write", provider_id="provider-a", idempotency_key="key-1")
        ])])
        asyncio.run(engine.pause_workflow(workflow_id, "network outage"))
        assert engine.get_workflow_state(workflow_id) == WorkflowState.WAITING_FOR_NETWORK
        asyncio.run(engine.resume_workflow(workflow_id))
        assert adapter.calls == [("write", "key-1")]
    finally:
        temporary_directory.cleanup()