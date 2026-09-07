import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from atrin_core.database import AtrinDatabase
from atrin_core.models import Step, Task, WorkflowState
from atrin_core.session_manager import SessionManager
from atrin_core.workflow_engine import WorkflowEngine


class MockAdapter:
    def __init__(self, verification="CONFIRMED", fail=False, cancel_result=False):
        self.verification = verification
        self.fail = fail
        self.cancel_result = cancel_result
        self.calls = []

    async def execute(self, action, idempotency_key, *, operation_id=None, fencing_token=None):
        self.calls.append((action, idempotency_key, operation_id, fencing_token))
        if self.fail:
            raise RuntimeError("network failure after dispatch")
        return {"result": "ok", "evidence": "receipt"}

    async def verify_action(self, idempotency_key, *, operation_id=None):
        return self.verification

    async def cancel(self, idempotency_key, *, operation_id=None):
        return self.cancel_result


def build_engine(adapter=None, protected=False):
    temporary_directory = tempfile.TemporaryDirectory()
    database = AtrinDatabase(os.path.join(temporary_directory.name, "workflow.db"))
    adapter = adapter or MockAdapter()
    session_manager = SessionManager(database) if protected else None
    engine = WorkflowEngine(database, {"provider-a": adapter}, session_manager=session_manager)
    return temporary_directory, database, engine, adapter


def make_workflow(engine, key="key-1", protected=False):
    return engine.create_workflow(
        "ship",
        [Task(task_id="task-1", description="do", steps=[
            Step(step_id="step-1", action="write", provider_id="provider-a", idempotency_key=key,
                 provider_profile_id="profile-1" if protected else None, side_effecting=protected)
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
        operation_id = connection.execute("SELECT operation_id FROM steps WHERE step_id='step-1'").fetchone()[0]
        assert operation_id
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_create_workflow_is_idempotent_for_client_request():
    temporary_directory, database, engine, _ = build_engine()
    try:
        first = engine.create_workflow("ship", [Task(task_id="task-1", description="do")], client_request_id="request-1")
        second = engine.create_workflow("ship", [Task(task_id="task-2", description="do")], client_request_id="request-1")
        assert first == second
        connection = database.get_connection()
        assert connection.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 1
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
        assert len(adapter.calls) == 1
        assert adapter.calls[0][1] == "key-1"
        assert adapter.calls[0][2]
        connection = database.get_connection()
        assert connection.execute("SELECT status FROM idempotency_ledger WHERE idempotency_key='key-1'").fetchone()[0] == "CONFIRMED"
        assert connection.execute("SELECT status FROM steps WHERE step_id='step-1'").fetchone()[0] == "CONFIRMED"
        assert engine.get_workflow_state(workflow_id) == WorkflowState.COMPLETED
        assert engine.validate_audit_chain() is True
        connection.close()
    finally:
        temporary_directory.cleanup()


def test_protected_step_requires_and_uses_exclusive_fence():
    adapter = MockAdapter("CONFIRMED")
    temporary_directory, database, engine, _ = build_engine(adapter, protected=True)
    try:
        workflow_id = make_workflow(engine, protected=True)
        engine.session_manager.create_profile("profile-1", "provider-a", "account-1", "Profile")
        result = asyncio.run(engine.execute_step(workflow_id, "step-1"))
        assert result["result"] == "ok"
        connection = database.get_connection()
        row = connection.execute("SELECT fencing_token, side_effecting FROM steps WHERE step_id='step-1'").fetchone()
        assert row["fencing_token"] == 1
        assert row["side_effecting"] == 1
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
                Step(step_id="step-2", action="write", provider_id="provider-a", idempotency_key="shared-key", side_effecting=False)
            ])],
        )
        asyncio.run(engine.execute_step(workflow_a, "step-1"))
        with pytest.raises(RuntimeError, match="collision"):
            asyncio.run(engine.execute_step(workflow_b, "step-2"))
    finally:
        temporary_directory.cleanup()


def test_resume_confirmed_action_skips_execution():
    adapter = MockAdapter("CONFIRMED")
    temporary_directory, database, engine, _ = build_engine(adapter)
    try:
        workflow_id = make_workflow(engine)
        connection = database.get_connection()
        operation_id = connection.execute("SELECT operation_id FROM steps WHERE step_id='step-1'").fetchone()[0]
        connection.execute(
            "INSERT INTO idempotency_ledger(idempotency_key,workflow_id,step_id,provider_id,operation_id,status,confirmed_at) VALUES (?,?,?,?,?,'CONFIRMED',CURRENT_TIMESTAMP)",
            ("key-1", workflow_id, "step-1", "provider-a", operation_id),
        )
        connection.commit()
        connection.close()
        result = asyncio.run(engine.resume_workflow(workflow_id, {
            "step_id": "step-1", "provider_id": "provider-a",
            "action_idempotency_key": "key-1", "operation_id": operation_id, "state": "WAITING_FOR_NETWORK",
        }, skip_action=True))
        assert result["state"] == "COMPLETED"
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
        operation_id = connection.execute("SELECT operation_id FROM steps WHERE step_id='step-1'").fetchone()[0]
        expired = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        connection.execute(
            "INSERT INTO idempotency_ledger(idempotency_key, workflow_id, step_id, provider_id, operation_id, status, expires_at, claim_owner, attempt) VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', ?, ?, 1)",
            ("key-1", workflow_id, "step-1", "provider-a", operation_id, expired, "dead-worker"),
        )
        connection.execute("UPDATE steps SET status='EXECUTING' WHERE step_id='step-1'")
        connection.commit()
        connection.close()
        asyncio.run(engine.execute_step(workflow_id, "step-1"))
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
        operation_id = connection.execute("SELECT operation_id FROM steps WHERE step_id='step-1'").fetchone()[0]
        expired = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        connection.execute(
            "INSERT INTO idempotency_ledger(idempotency_key, workflow_id, step_id, provider_id, operation_id, status, expires_at, claim_owner, attempt) VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', ?, ?, 1)",
            ("key-1", workflow_id, "step-1", "provider-a", operation_id, expired, "dead-worker"),
        )
        connection.commit()
        connection.close()
        with pytest.raises(RuntimeError, match="ambiguous"):
            asyncio.run(engine.execute_step(workflow_id, "step-1"))
        connection = database.get_connection()
        assert connection.execute("SELECT status FROM idempotency_ledger WHERE idempotency_key='key-1'").fetchone()[0] == "AMBIGUOUS"
        assert connection.execute("SELECT status FROM steps WHERE step_id='step-1'").fetchone()[0] == "AMBIGUOUS"
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
        assert adapter.calls
    finally:
        temporary_directory.cleanup()


def test_cancel_requires_provider_confirmation_when_action_is_running():
    adapter = MockAdapter("CONFIRMED", cancel_result=False)
    temporary_directory, database, engine, _ = build_engine(adapter, protected=True)
    try:
        engine.session_manager.create_profile("profile-1", "provider-a", "account-1", "Profile")
        workflow_id = make_workflow(engine, protected=True)
        connection = database.get_connection()
        operation_id = connection.execute("SELECT operation_id FROM steps WHERE step_id='step-1'").fetchone()[0]
        connection.execute("UPDATE workflows SET state='EXECUTING' WHERE workflow_id=?", (workflow_id,))
        connection.execute("UPDATE steps SET status='EXECUTING' WHERE step_id='step-1'")
        connection.execute(
            "INSERT INTO idempotency_ledger(idempotency_key,workflow_id,step_id,provider_id,operation_id,status,claim_owner,attempt) VALUES (?,?,?,?,?,'IN_PROGRESS','worker',1)",
            ("key-1", workflow_id, "step-1", "provider-a", operation_id),
        )
        connection.commit()
        connection.close()
        with pytest.raises(RuntimeError, match="did not confirm cancellation"):
            asyncio.run(engine.cancel_workflow(workflow_id))
        assert engine.get_workflow_state(workflow_id) == WorkflowState.WAITING_FOR_PROVIDER
    finally:
        temporary_directory.cleanup()
