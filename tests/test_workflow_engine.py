import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from atrin_core.database import AtrinDatabase
from atrin_core.models import Step, Task, WorkflowState
from atrin_core.workflow_engine import WorkflowEngine


class MockAdapter:
    def __init__(self, verification="NOT_STARTED", fail=False):
        self.verification = verification
        self.fail = fail
        self.calls = []

    async def execute(self, action, idempotency_key, *, fencing_token=None):
        self.calls.append((action, idempotency_key, fencing_token))
        if self.fail:
            raise RuntimeError("network failure after dispatch")
        return {"result": "ok", "evidence": "receipt"}

    async def verify_action(self, idempotency_key):
        return self.verification


def build_engine(adapter=None):
    temporary_directory = tempfile.TemporaryDirectory()
    database = AtrinDatabase(os.path.join(temporary_directory.name, "workflow.db"))
    adapter = adapter or MockAdapter()
    engine = WorkflowEngine(database, {"provider-a": adapter})
    return temporary_directory, database, engine, adapter


def make_workflow(engine, key="key-1"):
    return engine.create_workflow(
        "ship",
        [Task(task_id="task-1", description="do", steps=[
            Step(step_id="step-1", action="write", provider_id="provider-a", idempotency_key=key)
        ])],
    )


def test_create_workflow_and_state():
    temporary_directory, database, engine, _ = build_engine()
    try:
        workflow_id = make_workflow(engine)
        assert engine.get_workflow_state(workflow_id) == WorkflowState.IDLE
        connection = database.get_connection()
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_log WHERE workflow_id=?", (workflow_id,)).fetchone()[0] == 1
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_execute_step_confirms_and_is_idempotent():
    temporary_directory, database, engine, adapter = build_engine()
    try:
        workflow_id = make_workflow(engine)
        first = asyncio.run(engine.execute_step(workflow_id, "step-1"))
        second = asyncio.run(engine.execute_step(workflow_id, "step-1"))
        assert first["result"] == "ok"
        assert second["result"] == "ok"
        assert adapter.calls == [("write", "key-1", None)]
        connection = database.get_connection()
        assert connection.execute("SELECT status FROM idempotency_ledger WHERE idempotency_key='key-1'").fetchone()[0] == "CONFIRMED"
        assert connection.execute("SELECT status FROM steps WHERE step_id='step-1'").fetchone()[0] == "CONFIRMED"
        assert engine.get_workflow_state(workflow_id) == WorkflowState.COMPLETED
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_idempotency_collision_is_rejected():
    temporary_directory, _, engine, _ = build_engine()
    try:
        workflow_a = make_workflow(engine, key="shared-key")
        workflow_b = engine.create_workflow(
            "another",
            [Task(task_id="task-2", description="other", steps=[
                Step(step_id="step-2", action="write", provider_id="provider-a", idempotency_key="shared-key")
            ])],
        )
        asyncio.run(engine.execute_step(workflow_a, "step-1"))
        with pytest.raises(RuntimeError, match="collision"):
            asyncio.run(engine.execute_step(workflow_b, "step-2"))
    finally:
        temporary_directory.cleanup()


def test_resume_confirmed_action_skips_execution():
    adapter = MockAdapter("CONFIRMED")
    temporary_directory, _, engine, _ = build_engine(adapter)
    try:
        workflow_id = make_workflow(engine)
        asyncio.run(engine.save(workflow_id, {
            "step_id": "step-1", "provider_id": "provider-a",
            "action_idempotency_key": "key-1", "state": "WAITING_FOR_NETWORK",
        }))
        result = asyncio.run(engine.resume_workflow(workflow_id))
        assert result.skipped_action is True
        assert adapter.calls == []
        assert engine.get_workflow_state(workflow_id) == WorkflowState.COMPLETED
    finally:
        temporary_directory.cleanup()


def test_expired_in_progress_is_verified_before_replay():
    adapter = MockAdapter("NOT_STARTED")
    temporary_directory, database, engine, _ = build_engine(adapter)
    try:
        workflow_id = make_workflow(engine)
        connection = database.get_connection()
        expired = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        connection.execute(
            "INSERT INTO idempotency_ledger(idempotency_key, workflow_id, step_id, provider_id, status, expires_at, claim_owner, attempt) "
            "VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?, ?, 1)",
            ("key-1", workflow_id, "step-1", "provider-a", expired, "dead-worker"),
        )
        connection.execute("UPDATE steps SET status='EXECUTING' WHERE step_id='step-1'")
        connection.commit()
        connection.close()

        asyncio.run(engine.execute_step(workflow_id, "step-1"))
        assert adapter.calls == [("write", "key-1", None)]
        connection = database.get_connection()
        row = connection.execute("SELECT status, attempt FROM idempotency_ledger WHERE idempotency_key='key-1'").fetchone()
        assert row["status"] == "CONFIRMED"
        assert row["attempt"] == 2
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_expired_in_progress_with_ambiguous_verifier_pauses_workflow():
    adapter = MockAdapter("IN_PROGRESS")
    temporary_directory, database, engine, _ = build_engine(adapter)
    try:
        workflow_id = make_workflow(engine)
        connection = database.get_connection()
        expired = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        connection.execute(
            "INSERT INTO idempotency_ledger(idempotency_key, workflow_id, step_id, provider_id, status, expires_at, claim_owner, attempt) "
            "VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?, ?, 1)",
            ("key-1", workflow_id, "step-1", "provider-a", expired, "dead-worker"),
        )
        connection.commit()
        connection.close()
        with pytest.raises(RuntimeError, match="ambiguous"):
            asyncio.run(engine.execute_step(workflow_id, "step-1"))
        connection = database.get_connection()
        assert connection.execute("SELECT status FROM idempotency_ledger WHERE idempotency_key='key-1'").fetchone()[0] == "AMBIGUOUS"
        assert engine.get_workflow_state(workflow_id) == WorkflowState.WAITING_FOR_PROVIDER
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_external_failure_becomes_ambiguous_not_retryable_failed():
    adapter = MockAdapter(fail=True)
    temporary_directory, database, engine, _ = build_engine(adapter)
    try:
        workflow_id = make_workflow(engine)
        with pytest.raises(RuntimeError, match="ambiguous"):
            asyncio.run(engine.execute_step(workflow_id, "step-1"))
        connection = database.get_connection()
        assert connection.execute("SELECT status FROM idempotency_ledger WHERE idempotency_key='key-1'").fetchone()[0] == "AMBIGUOUS"
        assert engine.get_workflow_state(workflow_id) == WorkflowState.WAITING_FOR_PROVIDER
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_pause_and_resume_cycle():
    temporary_directory, _, engine, adapter = build_engine()
    try:
        workflow_id = make_workflow(engine)
        asyncio.run(engine.pause_workflow(workflow_id, "network outage"))
        assert engine.get_workflow_state(workflow_id) == WorkflowState.WAITING_FOR_NETWORK
        asyncio.run(engine.resume_workflow(workflow_id))
        assert adapter.calls == [("write", "key-1", None)]
    finally:
        temporary_directory.cleanup()
