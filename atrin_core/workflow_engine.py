"""Durable, vendor-neutral workflow orchestration."""

import inspect
import json
import uuid
from datetime import datetime, timezone, timedelta
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
    """Vendor-neutral durable workflow engine."""

    _CLAIM_LEASE_SECONDS = 300

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
            SELECT s.*, t.workflow_id, t.order_index AS task_order
            FROM steps s JOIN tasks t ON t.task_id = s.task_id
            WHERE s.step_id = ? AND t.workflow_id = ?
        """, (step_id, workflow_id)).fetchone()
        if row is None:
            raise LookupError(f"Step not found: {step_id}")
        return row

    def _assert_step_runnable(self, connection: Any, workflow_id: str, step: Any) -> None:
        workflow = connection.execute(
            "SELECT state FROM workflows WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
        if workflow is None:
            raise LookupError(f"Workflow not found: {workflow_id}")
        if workflow["state"] == WorkflowState.CANCELLED.value:
            raise RuntimeError("Workflow is cancelled")
        if workflow["state"] == WorkflowState.COMPLETED.value:
            raise RuntimeError("Workflow is already completed")

        previous_task = connection.execute("""
            SELECT task_id FROM tasks
            WHERE workflow_id = ? AND order_index < ? AND status != 'COMPLETED'
            ORDER BY order_index LIMIT 1
        """, (workflow_id, step["task_order"])).fetchone()
        if previous_task is not None:
            raise RuntimeError(f"Previous task is not completed: {previous_task['task_id']}")

        previous_step = connection.execute("""
            SELECT step_id FROM steps
            WHERE task_id = ? AND order_index < ? AND status != 'CONFIRMED'
            ORDER BY order_index LIMIT 1
        """, (step["task_id"], step["order_index"])).fetchone()
        if previous_step is not None:
            raise RuntimeError(f"Previous step is not confirmed: {previous_step['step_id']}")

    async def _verify_existing_action(self, adapter: ActionAdapter, key: str) -> str:
        status = await _call(adapter.verify_action, key)
        return str(status).upper()

    async def execute_step(self, workflow_id: str, step_id: str) -> Any:
        connection = self.database.get_connection()
        try:
            step = self._step(connection, workflow_id, step_id)
            self._assert_step_runnable(connection, workflow_id, step)
            adapter = self.adapters.get(step["provider_id"])
            if adapter is None:
                raise LookupError(f"No adapter registered for provider: {step['provider_id']}")

            ledger = connection.execute(
                "SELECT status, expires_at FROM idempotency_ledger WHERE idempotency_key = ?",
                (step["idempotency_key"],),
            ).fetchone()
            if ledger and ledger["status"] == "CONFIRMED":
                existing = connection.execute(
                    "SELECT result, evidence FROM steps WHERE step_id = ?", (step_id,)
                ).fetchone()
                return {"result": existing["result"], "evidence": existing["evidence"]}

            if ledger and ledger["status"] in {"PENDING", "IN_PROGRESS"}:
                verified = await self._verify_existing_action(adapter, step["idempotency_key"])
                if verified == "CONFIRMED":
                    connection.execute(
                        "UPDATE steps SET status='CONFIRMED' WHERE step_id=?", (step_id,)
                    )
                    connection.execute(
                        "UPDATE idempotency_ledger SET status='CONFIRMED', confirmed_at=CURRENT_TIMESTAMP, expires_at=NULL WHERE idempotency_key=?",
                        (step["idempotency_key"],),
                    )
                    connection.commit()
                    return await self.execute_step(workflow_id, step_id)
                if verified not in {"NOT_STARTED", "FAILED"}:
                    raise RuntimeError(
                        f"Action {step['idempotency_key']} cannot be safely replayed; verifier returned {verified}"
                    )

            connection.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc)
            expires = (now + timedelta(seconds=self._CLAIM_LEASE_SECONDS)).isoformat()
            if ledger is None:
                connection.execute("""
                    INSERT INTO idempotency_ledger
                    (idempotency_key, workflow_id, step_id, provider_id, status, expires_at)
                    VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?)
                """, (step["idempotency_key"], workflow_id, step_id, step["provider_id"], expires))
            else:
                cursor = connection.execute("""
                    UPDATE idempotency_ledger
                    SET status='IN_PROGRESS', expires_at=?
                    WHERE idempotency_key=? AND status IN ('PENDING','FAILED')
                """, (expires, step["idempotency_key"]))
                if cursor.rowcount != 1:
                    raise RuntimeError("Workflow step is already claimed by another execution")

            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (WorkflowState.EXECUTING.value, workflow_id),
            )
            connection.execute(
                "UPDATE steps SET status='EXECUTING' WHERE step_id=?", (step_id,)
            )
            self._checkpoint(connection, workflow_id, {
                "task_id": step["task_id"], "step_id": step_id,
                "state": WorkflowState.EXECUTING.value,
                "current_action": step["action"], "provider_id": step["provider_id"],
                "action_idempotency_key": step["idempotency_key"],
                "last_result": None, "evidence": None, "checkpoint_version": 1,
            })
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
            current = connection.execute(
                "SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            if current is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if current["state"] == WorkflowState.CANCELLED.value:
                connection.execute(
                    "UPDATE steps SET status=?, result=?, evidence=? WHERE step_id=? AND status='EXECUTING'",
                    ("CANCELLED" if status == "CONFIRMED" else "FAILED", str(result_value), evidence, step_id),
                )
                connection.execute(
                    "UPDATE idempotency_ledger SET status=? WHERE idempotency_key=? AND status='IN_PROGRESS'",
                    ("CONFIRMED" if status == "CONFIRMED" else "FAILED", step["idempotency_key"]),
                )
                connection.commit()
                raise RuntimeError("Workflow was cancelled while the external action was running")

            connection.execute(
                "UPDATE steps SET status=?, result=?, evidence=? WHERE step_id=? AND status='EXECUTING'",
                (status, str(result_value), evidence, step_id),
            )
            if status == "CONFIRMED":
                connection.execute(
                    "UPDATE idempotency_ledger SET status='CONFIRMED', confirmed_at=CURRENT_TIMESTAMP, expires_at=NULL WHERE idempotency_key=? AND status='IN_PROGRESS'",
                    (step["idempotency_key"],),
                )
                task_counts = connection.execute(
                    "SELECT COUNT(*) AS total, SUM(CASE WHEN status='CONFIRMED' THEN 1 ELSE 0 END) AS done FROM steps WHERE task_id=?",
                    (step["task_id"],),
                ).fetchone()
                if task_counts["total"] and task_counts["done"] == task_counts["total"]:
                    connection.execute("UPDATE tasks SET status='COMPLETED' WHERE task_id=?", (step["task_id"],))
                remaining = connection.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!='COMPLETED'",
                    (workflow_id,),
                ).fetchone()["n"]
                next_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
            else:
                connection.execute(
                    "UPDATE idempotency_ledger SET status='FAILED', expires_at=NULL WHERE idempotency_key=? AND status='IN_PROGRESS'",
                    (step["idempotency_key"],),
                )
                next_state = WorkflowState.FAILED

            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (next_state.value, workflow_id),
            )
            self._checkpoint(connection, workflow_id, {
                "task_id": step["task_id"], "step_id": step_id,
                "state": next_state.value,
                "current_action": step["action"], "provider_id": step["provider_id"],
                "action_idempotency_key": step["idempotency_key"],
                "last_result": str(result_value), "evidence": evidence, "checkpoint_version": 1,
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
                    WHERE t.workflow_id = ? AND s.status IN ('PENDING','EXECUTING')
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
            if adapter is None:
                raise LookupError(f"No adapter registered for provider: {checkpoint.get('provider_id')}")
            recovery_engine = RecoveryEngine(
                checkpoint_store=self,
                workflow_controller=self,
                external_state_verifier=adapter,
            )
            return await recovery_engine.resume_from_checkpoint(workflow_id)

        checkpoint = dict(checkpoint)
        connection = self.database.get_connection()
        try:
            step = self._step(connection, workflow_id, checkpoint.get("step_id", ""))
            if checkpoint.get("provider_id") not in (None, step["provider_id"]):
                raise ValueError("Checkpoint provider does not match the durable step")
            if checkpoint.get("action_idempotency_key") not in (None, step["idempotency_key"]):
                raise ValueError("Checkpoint idempotency key does not match the durable step")
            checkpoint["provider_id"] = step["provider_id"]
            checkpoint["action_idempotency_key"] = step["idempotency_key"]

            if skip_action:
                # The external verifier has already established that the side
                # effect happened. Persist that fact instead of leaving the
                # workflow stuck in RECOVERING.
                connection.execute("UPDATE steps SET status='CONFIRMED' WHERE step_id=?", (step["step_id"],))
                connection.execute("UPDATE idempotency_ledger SET status='CONFIRMED', confirmed_at=CURRENT_TIMESTAMP, expires_at=NULL WHERE idempotency_key=?", (step["idempotency_key"],))
                connection.execute("UPDATE tasks SET status='COMPLETED' WHERE task_id=? AND NOT EXISTS (SELECT 1 FROM steps WHERE task_id=? AND status!='CONFIRMED')", (step["task_id"], step["task_id"]))
                remaining = connection.execute("SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!='COMPLETED'", (workflow_id,)).fetchone()["n"]
                final_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
                connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?", (final_state.value, workflow_id))
                checkpoint["state"] = final_state.value
                self._checkpoint(connection, workflow_id, checkpoint)
                connection.commit()
                return checkpoint

            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id = ?", (WorkflowState.RECOVERING.value, workflow_id))
            checkpoint["state"] = WorkflowState.RECOVERING.value
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        finally:
            connection.close()
        return await self.execute_step(workflow_id, checkpoint["step_id"])

    async def cancel_workflow(self, workflow_id: str) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("UPDATE workflows SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE workflow_id = ?", (WorkflowState.CANCELLED.value, workflow_id))
            checkpoint = await self.load(workflow_id) or {"workflow_id": workflow_id}
            checkpoint["state"] = WorkflowState.CANCELLED.value
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        finally:
            connection.close()
