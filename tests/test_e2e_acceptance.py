import asyncio

import pytest

from atrin_core.database import AtrinDatabase
from atrin_core.models import Step, Task, WorkflowState
from atrin_core.session_manager import SessionManager
from atrin_core.workflow_engine import WorkflowEngine


class MockWorkflowAdapter:
    def __init__(self):
        self.calls = []
        self.fail_next = False
        self.verification = "NOT_STARTED"

    async def execute(self, action, idempotency_key, *, fencing_token=None):
        self.calls.append((action, idempotency_key, fencing_token))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Simulated network failure after dispatch")
        return {"result": "ok", "evidence": f"{action} executed successfully"}

    async def verify_action(self, idempotency_key):
        return self.verification


def test_complete_provider_lifecycle_workflow_recovery_and_audit(tmp_path):
    database = AtrinDatabase(str(tmp_path / "acceptance.db"))
    manager = SessionManager(database)
    provider_id = "test-web-provider"
    profile_id = "profile-test-web-provider"
    manager.create_profile(profile_id, provider_id, "acct-001", "Test Web Provider")

    adapter = MockWorkflowAdapter()
    engine = WorkflowEngine(database, {provider_id: adapter}, session_manager=manager)

    workflow = [
        Task(
            task_id="task-collect-data",
            description="Collect provider data",
            steps=[
                Step(step_id="step-fetch-users", action="fetch_users", provider_id=provider_id,
                     idempotency_key="fetch-users-key", provider_profile_id=profile_id),
                Step(step_id="step-sync-data", action="sync_data", provider_id=provider_id,
                     idempotency_key="sync-data-key", provider_profile_id=profile_id),
            ],
        ),
        Task(
            task_id="task-validate-output",
            description="Validate output",
            steps=[
                Step(step_id="step-verify-results", action="verify_results", provider_id=provider_id,
                     idempotency_key="verify-results-key", provider_profile_id=profile_id)
            ],
        ),
    ]

    workflow_id = engine.create_workflow("Complete provider lifecycle and workflow execution", workflow)
    token = manager.acquire_lock(profile_id, workflow_id)
    connection = database.get_connection()
    connection.execute("UPDATE steps SET fencing_token=? WHERE provider_profile_id=?", (token, profile_id))
    connection.commit()
    connection.close()

    asyncio.run(engine.execute_step(workflow_id, "step-fetch-users"))
    assert engine.get_workflow_state(workflow_id) == WorkflowState.OBSERVING

    adapter.fail_next = True
    with pytest.raises(RuntimeError, match="ambiguous"):
        asyncio.run(engine.execute_step(workflow_id, "step-sync-data"))
    assert engine.get_workflow_state(workflow_id) == WorkflowState.WAITING_FOR_PROVIDER

    connection = database.get_connection()
    ambiguous = connection.execute(
        "SELECT status FROM idempotency_ledger WHERE idempotency_key='sync-data-key'"
    ).fetchone()[0]
    assert ambiguous == "AMBIGUOUS"

    adapter.verification = "CONFIRMED"
    recovery = asyncio.run(engine.recovery_engine.resume_from_checkpoint(workflow_id))
    assert recovery.resumed is True
    assert recovery.skipped_action is True
    assert engine.get_workflow_state(workflow_id) == WorkflowState.OBSERVING

    asyncio.run(engine.execute_step(workflow_id, "step-verify-results"))
    assert engine.get_workflow_state(workflow_id) == WorkflowState.COMPLETED

    calls_for_sync = [call for call in adapter.calls if call[1] == "sync-data-key"]
    # The failed dispatch is attempted once; verified recovery must not replay it.
    assert len(calls_for_sync) == 1
    assert all(call[2] == token for call in adapter.calls)

    workflow_audit = connection.execute(
        "SELECT event_type FROM audit_log WHERE workflow_id=? ORDER BY seq", (workflow_id,)
    ).fetchall()
    events = [row[0] for row in workflow_audit]
    assert "WORKFLOW_CREATED" in events
    assert events.count("ACTION_CLAIMED") >= 3
    assert events.count("ACTION_CONFIRMED") >= 2
    assert "ACTION_AMBIGUOUS" in events
    assert "ACTION_CONFIRMED_BY_VERIFIER" in events

    connection.execute(
        "DELETE FROM steps WHERE task_id IN (SELECT task_id FROM tasks WHERE workflow_id=?)", (workflow_id,)
    )
    connection.execute("DELETE FROM tasks WHERE workflow_id=?", (workflow_id,))
    connection.execute("DELETE FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,))
    connection.execute("DELETE FROM sync_metadata WHERE workflow_id=?", (workflow_id,))
    connection.execute("DELETE FROM audit_log WHERE workflow_id=?", (workflow_id,))
    connection.execute("DELETE FROM workflows WHERE workflow_id=?", (workflow_id,))
    connection.execute("DELETE FROM sessions WHERE provider_profile_id=?", (profile_id,))
    connection.execute("DELETE FROM provider_profiles WHERE id=?", (profile_id,))
    connection.commit()
    connection.close()
