"""Runtime hardening for workflow admission, state transitions, and recovery races."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .models import ExecutionStatus, WorkflowState
from .state_machine import assert_workflow_transition


_VERIFICATION_STATE = "VERIFYING"
_VERIFICATION_LEASE_SECONDS = 60


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

    engine_type: Any = WorkflowEngine
    if getattr(engine_type, "_atrin_hardening_installed", False):
        return

    original_assert = engine_type._assert_step_runnable
    original_pause = engine_type.pause_workflow
    original_resume = engine_type.resume_workflow
    original_cancel = engine_type.cancel_workflow
    original_execute = engine_type.execute_step

    def hardened_assert(self: Any, connection: Any, workflow_id: str, step: Any) -> None:
        workflow = connection.execute(
            "SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        state = workflow["state"] if workflow is not None else None
        if state == WorkflowState.COMPLETED.value:
            ledger = connection.execute(
                "SELECT status FROM idempotency_ledger WHERE idempotency_key=? AND workflow_id=? AND step_id=? LIMIT 1",
                (step["idempotency_key"], workflow_id, step["step_id"]),
            ).fetchone()
            if ledger is not None and ledger["status"] == ExecutionStatus.CONFIRMED.value:
                return
        if state in {
            WorkflowState.WAITING_FOR_AUTH.value,
            WorkflowState.WAITING_FOR_NETWORK.value,
            WorkflowState.WAITING_FOR_HUMAN_INTERACTION.value,
            WorkflowState.WAITING_FOR_HUMAN_APPROVAL.value,
            WorkflowState.WAITING_FOR_PROVIDER.value,
            WorkflowState.CANCELLING.value,
            WorkflowState.CANCELLED.value,
            WorkflowState.COMPLETED.value,
        }:
            raise RuntimeError(f"Workflow is not executable from state: {state}")
        original_assert(self, connection, workflow_id, step)

    async def hardened_pause(self: Any, workflow_id: str, reason: str) -> None:
        current = _state(self, workflow_id)
        target = _pause_target(reason)
        if current != target:
            assert_workflow_transition(current, target)
        await original_pause(self, workflow_id, reason)

    async def hardened_resume(
        self: Any,
        workflow_id: str,
        checkpoint: Mapping[str, Any] | None = None,
        skip_action: bool = False,
    ) -> Any:
        current = _state(self, workflow_id)
        if skip_action:
            if current in {
                WorkflowState.COMPLETED,
                WorkflowState.WAITING_FOR_AUTH,
                WorkflowState.WAITING_FOR_NETWORK,
                WorkflowState.WAITING_FOR_PROVIDER,
                WorkflowState.WAITING_FOR_HUMAN_INTERACTION,
                WorkflowState.WAITING_FOR_HUMAN_APPROVAL,
                WorkflowState.FAILED,
                WorkflowState.RECOVERING,
                WorkflowState.IDLE,
            }:
                return await original_resume(self, workflow_id, checkpoint, skip_action)
        elif current != WorkflowState.RECOVERING:
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
        }:
            raise RuntimeError(f"Workflow is not executable from state: {current.value}")

        connection = self.database.get_connection()
        try:
            row = connection.execute(
                """
                SELECT s.idempotency_key, s.operation_id, s.provider_id,
                       l.status, l.expires_at, l.claim_owner
                FROM steps s
                JOIN tasks t ON t.task_id=s.task_id
                LEFT JOIN idempotency_ledger l ON l.idempotency_key=s.idempotency_key
                WHERE s.step_id=? AND t.workflow_id=?
                """,
                (step_id, workflow_id),
            ).fetchone()
        finally:
            connection.close()

        if row is not None and row["status"] == _VERIFICATION_STATE:
            if not _expired(row["expires_at"], self._now()):
                raise RuntimeError("External action verification is already in progress")

        verification_owner: str | None = None
        if row is not None and row["status"] in {
            ExecutionStatus.IN_PROGRESS.value,
            _VERIFICATION_STATE,
        } and _expired(row["expires_at"], self._now()):
            verification_owner = str(uuid.uuid4())
            verification_expires = (self._now() + timedelta(seconds=_VERIFICATION_LEASE_SECONDS)).isoformat()
            connection = self.database.get_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    UPDATE idempotency_ledger
                    SET status=?, claim_owner=?, expires_at=?
                    WHERE idempotency_key=? AND workflow_id=? AND step_id=?
                      AND status IN (?, ?)
                      AND expires_at<=?
                    """,
                    (
                        _VERIFICATION_STATE,
                        verification_owner,
                        verification_expires,
                        row["idempotency_key"],
                        workflow_id,
                        step_id,
                        ExecutionStatus.IN_PROGRESS.value,
                        _VERIFICATION_STATE,
                        self._now().isoformat(),
                    ),
                )
                connection.commit()
                if cursor.rowcount != 1:
                    raise RuntimeError("Expired workflow claim changed while verification ownership was acquired")
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

            adapter = self.adapters.get(row["provider_id"])
            if adapter is None:
                raise LookupError(f"No adapter registered for provider: {row['provider_id']}")
            verified = await self._verify_existing_action(
                adapter, row["idempotency_key"], row["operation_id"]
            )
            if verified == "CONFIRMED":
                return await self._finalize_verified_action(
                    workflow_id, step_id, row["idempotency_key"]
                )
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
                    """
                    UPDATE idempotency_ledger
                    SET status=?, expires_at=NULL, claim_owner=NULL
                    WHERE idempotency_key=? AND workflow_id=? AND step_id=?
                      AND status=? AND claim_owner=?
                    """,
                    (
                        ExecutionStatus.FAILED.value,
                        row["idempotency_key"],
                        workflow_id,
                        step_id,
                        _VERIFICATION_STATE,
                        verification_owner,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Workflow verification ownership changed before reclaim")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return await original_execute(self, workflow_id, step_id)

    engine_type._assert_step_runnable = hardened_assert
    engine_type.pause_workflow = hardened_pause
    engine_type.resume_workflow = hardened_resume
    engine_type.cancel_workflow = hardened_cancel
    engine_type.execute_step = hardened_execute
    engine_type._atrin_hardening_installed = True
