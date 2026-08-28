"""Durable, vendor-neutral workflow orchestration."""

import inspect
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .database import AtrinDatabase
from .models import Step, Task, WorkflowState
from .recovery_engine import RecoveryEngine


class ActionAdapter(Protocol):
    async def execute(self, action: str, idempotency_key: str) -> Any: ...
    async def verify_action(self, idempotency_key: str) -> str: ...


async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
    result = method(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


class WorkflowEngine:
    def __init__(self, database: AtrinDatabase, adapters: Mapping[str, ActionAdapter] | None = None):
        self.database = database
        self.adapters = dict(adapters or {})
        self.recovery_engine = RecoveryEngine(
            checkpoint_store=self,
            workflow_controller=self,
            external_state_verifier=None,
        )

    def _checkpoint(self, connection: Any, workflow_id: str, payload: Mapping[str, Any]) -> None:
        checkpoint = dict(payload)
        checkpoint.setdefault("workflow_id", workflow_id)
        checkpoint.setdefault("checkpoint_version", 1)
        connection.execute("""
            INSERT INTO workflow_checkpoints (workflow_id, checkpoint_version, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET
                checkpoint_version = excluded.checkpoint_version,
                payload = excluded.payload,
                updated_at = excluded.updated_at
        """, (workflow_id, checkpoint["checkpoint_version"], json.dumps(checkpoint),
               datetime.now(timezone.utc).isoformat()))

    async def save(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> None:
        connection = self.database.get_connection()
        try:
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        finally:
            connection.close()

    async def load(self, workflow_id: str) -> dict[str, Any] | None:
        connection = self.database.get_connection()
        try:
            row = connection.execute(
                "SELECT payload FROM workflow_checkpoints WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
            return json.loads(row["payload"]) if row else None
        finally:
            connection.close()

    def create_workflow(self, goal: str, plan: list[Task]) -> str:
        workflow_id = str(uuid.uuid4())
        connection = self.database.get_connection()
        try:
            connection.execute(
                "INSERT INTO workflows (workflow_id, goal, state) VALUES (?, ?, ?)",
                (workflow_id, goal, WorkflowState.IDLE.value),
            )
            for task_index, task in enumerate(plan):
                connection.execute(
                    "INSERT INTO tasks (task_id, workflow_id, description, status, order_index) VALUES (?, ?, ?, ?, ?)",
                    (task.task_id, workflow_id, task.description, task.status, task_index),
                )
                for step_index, step in enumerate(task.steps):
                    key = step.idempotency_key or str(uuid.uuid4())
                    step.idempotency_key = key
                    connection.execute(
                        "INSERT INTO steps (step_id, task_id, action, provider_id, idempotency_key, status, result, evidence, order_index) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (step.step_id, task.task_id, step.action, step.provider_id, key, step.status,
                         step.result, step.evidence, step_index),
                    )
            self._checkpoint(connection, workflow_id, {
                "workflow_id": workflow_id, "state": WorkflowState.IDLE.value,
                "goal": goal, "plan_version": 1, "completed_tasks": [],
                "pending_tasks": [task.task_id for task in plan], "failed_tasks": [],
            })
            connection.commit()
        finally:
            connection.close()
        return workflow_id

    def get_workflow_state(self, workflow_id: str) -> WorkflowState:
        connection = self.database.get_connection()
        try:
            row = connection.execute("SELECT state FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            if row is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            return WorkflowState(row["state"])
        finally:
            connection.close()

    def _step(self, connection: Any, workflow_id: str, step_id: str) -> Any:
        row = connection.execute("""
            SELECT s.*, t.workflow_id FROM steps s JOIN tasks t ON t.task_id = s.task_id
            WHERE s.step_id = ? AND t.workflow_id = ?
        """, (step_id, workflow_id)).fetchone()
        if row is None:
            raise LookupError(f"Step not found: {step_id}")
        return row

    async def execute_step(self, workflow_id: str, step_id: str) -> Any:
        connection = self.database.get_connection()
        try:
            step = self._step(connection, workflow_id, step_id)
            adapter = self.adapters.get(step["provider_id"])
            if adapter is None:
                raise LookupError(f"No adapter registered for provider: {step['provider_id']}")
            connection.execute("UPDATE workflows SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE workflow_id = ?",
                               (WorkflowState.EXECUTING.value, workflow_id))
            before = {"task_id": step["task_id"], "step_id": step_id, "state": WorkflowState.EXECUTING.value,
                      "current_action": step["action"], "provider_id": step["provider_id"],
                      "action_idempotency_key": step["idempotency_key"], "last_result": None,
                      "evidence": None, "checkpoint_version": 1}
            self._checkpoint(connection, workflow_id, before)
            connection.execute("""
                INSERT INTO idempotency_ledger (idempotency_key, workflow_id, step_id, provider_id, status)
                VALUES (?, ?, ?, ?, 'PENDING')
                ON CONFLICT(idempotency_key) DO UPDATE SET status = 'PENDING'
            """, (step["idempotency_key"], workflow_id, step_id, step["provider_id"]))
            connection.commit()
        finally:
            connection.close()

        try:
            result = await _call(adapter.execute, step["action"], step["idempotency_key"])
            evidence = result.get("evidence") if isinstance(result, dict) else None
            result_value = result.get("result", result) if isinstance(result, dict) else result
            status = "CONFIRMED"
        except Exception as error:
            result_value, evidence, status = str(error), None, "FAILED"

        connection = self.database.get_connection()
        try:
            connection.execute("UPDATE steps SET status = ?, result = ?, evidence = ? WHERE step_id = ?",
                               (status, str(result_value), evidence, step_id))
            connection.execute("UPDATE workflows SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE workflow_id = ?",
                               (WorkflowState.OBSERVING.value if status == "CONFIRMED" else WorkflowState.FAILED.value, workflow_id))
            connection.execute("""
                UPDATE idempotency_ledger SET status = ?, confirmed_at = CASE WHEN ? = 'CONFIRMED' THEN CURRENT_TIMESTAMP ELSE confirmed_at END
                WHERE idempotency_key = ?
            """, (status, status, step["idempotency_key"]))
            self._checkpoint(connection, workflow_id, {
                "task_id": step["task_id"], "step_id": step_id,
                "state": WorkflowState.OBSERVING.value if status == "CONFIRMED" else WorkflowState.FAILED.value,
                "current_action": step["action"], "provider_id": step["provider_id"],
                "action_idempotency_key": step["idempotency_key"], "last_result": str(result_value),
                "evidence": evidence, "checkpoint_version": 1,
            })
            connection.commit()
        finally:
            connection.close()
        if status == "FAILED":
            raise RuntimeError(str(result_value))
        return result

    async def pause_workflow(self, workflow_id: str, reason: str) -> None:
        normalized_reason = reason.lower()
        state = WorkflowState.WAITING_FOR_PROVIDER
        if "auth" in normalized_reason or "login" in normalized_reason:
            state = WorkflowState.WAITING_FOR_AUTH
        elif "network" in normalized_reason or "connect" in normalized_reason:
            state = WorkflowState.WAITING_FOR_NETWORK
        elif "approval" in normalized_reason:
            state = WorkflowState.WAITING_FOR_HUMAN_APPROVAL
        elif "human" in normalized_reason or "interaction" in normalized_reason:
            state = WorkflowState.WAITING_FOR_HUMAN_INTERACTION
        checkpoint = await self.load(workflow_id) or {"workflow_id": workflow_id}
        if "step_id" not in checkpoint:
            connection = self.database.get_connection()
            try:
                pending_step = connection.execute("""
                    SELECT s.step_id, s.task_id, s.action, s.provider_id, s.idempotency_key
                    FROM steps s JOIN tasks t ON t.task_id = s.task_id
                    WHERE t.workflow_id = ? AND s.status = 'PENDING'
                    ORDER BY t.order_index, s.order_index LIMIT 1
                """, (workflow_id,)).fetchone()
            finally:
                connection.close()
            if pending_step is not None:
                checkpoint.update({"step_id": pending_step["step_id"], "task_id": pending_step["task_id"],
                                   "current_action": pending_step["action"], "provider_id": pending_step["provider_id"],
                                   "action_idempotency_key": pending_step["idempotency_key"]})
        checkpoint.update({"state": state.value, "waiting_reason": reason})
        connection = self.database.get_connection()
        try:
            connection.execute("UPDATE workflows SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE workflow_id = ?", (state.value, workflow_id))
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        finally:
            connection.close()

    async def resume_workflow(self, workflow_id: str, checkpoint: Mapping[str, Any] | None = None,
                              skip_action: bool = False) -> Any:
        if checkpoint is None:
            checkpoint = await self.load(workflow_id)
            if checkpoint is None:
                raise LookupError(f"No checkpoint found for workflow {workflow_id}")
            adapter = self.adapters.get(checkpoint.get("provider_id"))
            recovery_engine = RecoveryEngine(
                checkpoint_store=self,
                workflow_controller=self,
                external_state_verifier=adapter,
            )
            result = await recovery_engine.resume_from_checkpoint(workflow_id)
            return result
        connection = self.database.get_connection()
        try:
            connection.execute("UPDATE workflows SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE workflow_id = ?",
                               (WorkflowState.RECOVERING.value, workflow_id))
            checkpoint = dict(checkpoint)
            checkpoint["state"] = WorkflowState.RECOVERING.value
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        finally:
            connection.close()
        if skip_action:
            return checkpoint
        return await self.execute_step(workflow_id, checkpoint["step_id"])

    async def cancel_workflow(self, workflow_id: str) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("UPDATE workflows SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE workflow_id = ?",
                               (WorkflowState.CANCELLED.value, workflow_id))
            checkpoint = await self.load(workflow_id) or {"workflow_id": workflow_id}
            checkpoint["state"] = WorkflowState.CANCELLED.value
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        finally:
            connection.close()