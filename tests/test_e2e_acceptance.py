import asyncio
import json
from pathlib import Path

from atrin_core.database import AtrinDatabase
from atrin_core.models import AuthState, Step, Task, WorkflowState
from atrin_core.session_manager import SessionManager
from atrin_core.workflow_engine import WorkflowEngine


class MockWorkflowAdapter:
    def __init__(self):
        self.calls = []
        self.fail_next = False
        self.verification = "NOT_STARTED"

    async def execute(self, action, idempotency_key):
        self.calls.append((action, idempotency_key))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Simulated network failure")
        return {"result": "ok", "evidence": f"{action} executed successfully"}

    async def verify_action(self, idempotency_key):
        return self.verification


def _append_audit_event(conn, workflow_id, event_type, actor, payload):
    conn.execute(
        """
        INSERT INTO audit_log (workflow_id, event_type, actor, payload, entry_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            workflow_id,
            event_type,
            actor,
            json.dumps(payload),
            f"{event_type}:{workflow_id}:{actor}:{payload.get('state', 'unknown')}",
        ),
    )


def test_complete_provider_lifecycle_and_workflow_execution(tmp_path):
    db_path = tmp_path / "acceptance.db"
    database = AtrinDatabase(str(db_path))
    manager = SessionManager(database)
    profile_id = "profile-test-web-provider"
    workflow_id = None
    provider_id = "test-web-provider"

    manager.create_profile(profile_id, provider_id, "acct-001", "Test Web Provider")

    conn = database.get_connection()
    initial = conn.execute(
        "SELECT auth_state FROM provider_profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()
    assert initial[0] == AuthState.UNKNOWN.value

    auth_sequence = [
        AuthState.UNKNOWN,
        AuthState.NOT_AUTHENTICATED,
        AuthState.LOGIN_REQUIRED,
        AuthState.AUTHENTICATING,
        AuthState.AUTHENTICATED,
        AuthState.ACTIVE,
    ]

    for index, state in enumerate(auth_sequence):
        conn.execute(
            "UPDATE provider_profiles SET auth_state = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (state.value, profile_id),
        )
        _append_audit_event(
            conn,
            "wf-e2e-acceptance",
            "AUTH_STATE_TRANSITION",
            "auth-engine",
            {"profile_id": profile_id, "from": auth_sequence[index - 1].value if index > 0 else AuthState.UNKNOWN.value, "to": state.value},
        )
    conn.commit()
    final_state = conn.execute(
        "SELECT auth_state FROM provider_profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()[0]
    assert final_state == AuthState.ACTIVE.value

    adapter = MockWorkflowAdapter()
    engine = WorkflowEngine(database, {provider_id: adapter})

    workflow = [
        Task(
            task_id="task-collect-data",
            description="Collect provider data",
            steps=[
                Step(
                    step_id="step-fetch-users",
                    action="fetch_users",
                    provider_id=provider_id,
                    idempotency_key="fetch-users-key",
                ),
                Step(
                    step_id="step-sync-data",
                    action="sync_data",
                    provider_id=provider_id,
                    idempotency_key="sync-data-key",
                ),
            ],
        ),
        Task(
            task_id="task-validate-output",
            description="Validate output",
            steps=[
                Step(
                    step_id="step-verify-results",
                    action="verify_results",
                    provider_id=provider_id,
                    idempotency_key="verify-results-key",
                )
            ],
        ),
    ]

    workflow_id = engine.create_workflow("Complete provider lifecycle and workflow execution", workflow)
    assert workflow_id is not None
    assert engine.get_workflow_state(workflow_id) == WorkflowState.IDLE

    for step in ["step-fetch-users", "step-sync-data", "step-verify-results"]:
        asyncio.run(engine.execute_step(workflow_id, step))

    assert adapter.calls == [
        ("fetch_users", "fetch-users-key"),
        ("sync_data", "sync-data-key"),
        ("verify_results", "verify-results-key"),
    ]

    conn = database.get_connection()
    conn.execute(
        "UPDATE idempotency_ledger SET status = 'PENDING', confirmed_at = NULL WHERE idempotency_key = 'sync-data-key'"
    )
    conn.execute(
        "UPDATE steps SET status = 'PENDING', result = NULL, evidence = NULL WHERE step_id = 'step-sync-data'"
    )
    conn.commit()

    adapter.fail_next = True
    checkpoint = asyncio.run(engine.load(workflow_id))
    checkpoint["state"] = WorkflowState.WAITING_FOR_NETWORK.value
    checkpoint["step_id"] = "step-sync-data"
    checkpoint["provider_id"] = provider_id
    checkpoint["action_idempotency_key"] = "sync-data-key"
    asyncio.run(engine.save(workflow_id, checkpoint))

    try:
        asyncio.run(engine.execute_step(workflow_id, "step-sync-data"))
    except RuntimeError as exc:
        assert "Simulated network failure" in str(exc)

    assert engine.get_workflow_state(workflow_id) == WorkflowState.FAILED

    recovery_checkpoint = asyncio.run(engine.load(workflow_id))
    recovery_checkpoint["state"] = WorkflowState.RECOVERING.value
    asyncio.run(engine.recovery_engine.handle_network_unavailable(workflow_id, recovery_checkpoint))
    assert engine.get_workflow_state(workflow_id) == WorkflowState.WAITING_FOR_NETWORK

    engine.recovery_engine.external_state_verifier = adapter
    adapter.verification = "CONFIRMED"
    adapter.fail_next = False
    adapter.calls = []
    restored_checkpoint = asyncio.run(engine.load(workflow_id))
    restored_checkpoint["state"] = WorkflowState.RECOVERING.value
    restored_checkpoint["provider_id"] = provider_id
    restored_checkpoint["action_idempotency_key"] = "sync-data-key"
    restored_checkpoint["step_id"] = "step-sync-data"

    resume_result = asyncio.run(engine.recovery_engine.resume_from_checkpoint(workflow_id))
    assert resume_result.skipped_action is True
    assert adapter.calls == []

    audit_rows = conn.execute(
        "SELECT event_type, payload FROM audit_log WHERE workflow_id = ? ORDER BY seq",
        ("wf-e2e-acceptance",),
    ).fetchall()
    assert len(audit_rows) >= 6
    assert any("AUTH_STATE_TRANSITION" in row[0] for row in audit_rows)

    conn.execute("DELETE FROM provider_profiles WHERE id = ?", (profile_id,))
    conn.execute("DELETE FROM workflows WHERE workflow_id = ?", (workflow_id,))
    conn.execute("DELETE FROM tasks WHERE workflow_id = ?", (workflow_id,))
    conn.execute("DELETE FROM steps WHERE task_id IN (SELECT task_id FROM tasks WHERE workflow_id = ?)", (workflow_id,))
    conn.execute("DELETE FROM workflow_checkpoints WHERE workflow_id = ?", (workflow_id,))
    conn.execute("DELETE FROM audit_log WHERE workflow_id = ?", ("wf-e2e-acceptance",))
    conn.commit()
    conn.close()
