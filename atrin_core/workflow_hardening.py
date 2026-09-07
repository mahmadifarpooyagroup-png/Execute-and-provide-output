"""Runtime hardening for workflow admission, state transitions, and recovery races."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .models import ExecutionStatus, WorkflowState
from .state_machine import assert_workflow_transition


def _pause_target(reason: str) -> WorkflowState:
    normalized = reason.lower()
    if "auth" in normalized or "login" in normalized:
        return WorkflowState.WAITING_FOR_AUTH
    if "network" in normalized or "connect" in normalized:
        return WorkflowState.WAITING_FOR_NETWORK
    if "approval" in normalized:
        return WorkflowState.WAITING_FOR_HUMAN_APPROVAL
    if "human" in normalized or "interaction" in normalized:
        return WorkflowState.WAITING_FOR_HUMAN_INTERACTION
    return WorkflowState.WAITING_FOR_PROVIDER


def _state(engine: Any, workflow_id: str) -> WorkflowState:
    return engine.get_workflow_state(workflow_id)


def _expired(value: Any, now: datetime) -> bool:
    if not value:
        return False
    if isinstance(value, (int, float)):
        expiry = datetime.fromtimestamp(value, tz=now.tzinfo)
    else:
        expiry = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=now.tzinfo)
    return expiry <= now


def install_workflow_hardening() -> None:
    from .workflow_engine import WorkflowEngine

    if getattr(WorkflowEngine, "_atrin_hardening_installed", False):
        return

    original_assert = WorkflowEngine._assert_step_runnable
    original_pause = WorkflowEngine.pause_workflow
    original_resume = WorkflowEngine.resume_workflow
    original_cancel = WorkflowEngine.cancel_workflow
    original_execute = WorkflowEngine.execute_step

    def hardened_assert(self: Any, connection: Any, workflow_id: str, step: Any) -> None:
        workflow = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
        if workflow is not None and workflow["state"] in {
            WorkflowState.WAITING_FOR_AUTH.value,
            WorkflowState.WAITING_FOR_NETWORK.value,
            WorkflowState.WAITING_FOR_HUMAN_INTERACTION.value,
            WorkflowState.WAITING_FOR_HUMAN_APPROVAL.value,
            WorkflowState.WAITING_FOR_PROVIDER.value,
            WorkflowState.CANCELLING.value,
            WorkflowState.CANCELLED.value,
            WorkflowState.COMPLETED.value,
        }:
            raise RuntimeError(f"Workflow is not executable from state: {workflow['state']}")
        original_assert(self, connection, workflow_id, step)

    async def hardened_pause(self: Any, workflow_id: str, reason: str) -> None:
        current = _state(self, workflow_id)
        target = _pause_target(reason)
        if current != target:
            assert_workflow_transition(current, target)
        await original_pause(self, workflow_id, reason)

    async def hardened_resume(self: Any, workflow_id: str, checkpoint: Mapping[str, Any] | None = None,
                              skip_action: bool = False) -> Any:
        current = _state(self, workflow_id)
        if current != WorkflowState.RECOVERING:
            assert_workflow_transition(current, WorkflowState.RECOVERING)
        return await original_resume(self, workflow_id, checkpoint, skip_action)

    async def hardened_cancel(self: Any, workflow_id: str) -> None:
        current = _state(self, workflow_id)
        if current in {WorkflowState.CANCELLED, WorkflowState.COMPLETED}:
            await original_cancel(self, workflow_id)
            return
        if current != WorkflowState.CANCELLING:
            assert_workflow_transition(current, WorkflowState.CANCELLING)
        await original_cancel(self, workflow_id)

    async def hardened_execute(self: Any, workflow_id: str, step_id: str) -> Any:
        current = _state(self, workflow_id)
        if current in {
            WorkflowState.WAITING_FOR_AUTH,
            WorkflowState.WAITING_FOR_NETWORK,
            WorkflowState.WAITING_FOR_HUMAN_INTERACTION,
            WorkflowState.WAITING_FOR_HUMAN_APPROVAL,
            WorkflowState.WAITING_FOR_PROVIDER,
            WorkflowState.CANCELLING,
            WorkflowState.CANCELLED,
            WorkflowState.COMPLETED,
        }:
            raise RuntimeError(f"Workflow is not executable from state: {current.value}")

        # Resolve expired claims before the engine opens its execution transaction.
        # This prevents a provider/network verification call from holding BEGIN IMMEDIATE.
        connection = self.database.get_connection()
        try:
            row = connection.execute(
                """
                SELECT s.idempotency_key, s.operation_id, s.provider_id, l.status, l.expires_at
                FROM steps s
                JOIN tasks t ON t.task_id=s.task_id
                LEFT JOIN idempotency_ledger l ON l.idempotency_key=s.idempotency_key
                WHERE s.step_id=? AND t.workflow_id=?
                """,
                (step_id, workflow_id),
            ).fetchone()
        finally:
            connection.close()

        if row is not None and row["status"] == ExecutionStatus.IN_PROGRESS.value and _expired(row["expires_at"], self._now()):
            adapter = self.adapters.get(row["provider_id"])
            if adapter is None:
                raise LookupError(f"No adapter registered for provider: {row['provider_id']}")
            verified = await self._verify_existing_action(adapter, row["idempotency_key"], row["operation_id"])
            if verified == "CONFIRMED":
                return await self._finalize_verified_action(workflow_id, step_id, row["idempotency_key"])
            if verified not in {"NOT_STARTED", "FAILED"}:
                self._mark_ambiguous(
                    workflow_id,
                    step_id,
                    row["idempotency_key"],
                    f"Verifier returned {verified} for expired claim",
                )
                raise RuntimeError("External action state is ambiguous; workflow paused for recovery")
            connection = self.database.get_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE idempotency_ledger SET status=?, expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND status=?",
                    (ExecutionStatus.FAILED.value, row["idempotency_key"], workflow_id, step_id, ExecutionStatus.IN_PROGRESS.value),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Expired workflow claim changed while being verified")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return await original_execute(self, workflow_id, step_id)

    WorkflowEngine._assert_step_runnable = hardened_assert
    WorkflowEngine.pause_workflow = hardened_pause
    WorkflowEngine.resume_workflow = hardened_resume
    WorkflowEngine.cancel_workflow = hardened_cancel
    WorkflowEngine.execute_step = hardened_execute
    WorkflowEngine._atrin_hardening_installed = True
