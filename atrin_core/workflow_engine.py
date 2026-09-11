"""Durable, vendor-neutral workflow orchestration."""

from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping, Protocol

from .database import AtrinDatabase
from .models import ExecutionStatus, StepStatus, TaskStatus, Task, WorkflowState
from .recovery_engine import RecoveryEngine


class ActionAdapter(Protocol):
    async def execute(
        self,
        action: str,
        idempotency_key: str,
        *,
        operation_id: str | None = None,
        fencing_token: int | None = None,
    ) -> Any: ...

    async def verify_action(
        self,
        idempotency_key: str,
        *,
        operation_id: str | None = None,
    ) -> str: ...

    async def cancel(
        self,
        idempotency_key: str,
        *,
        operation_id: str | None = None,
    ) -> bool: ...


async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
    result = method(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _supports_keyword(method: Any, name: str) -> bool:
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == name for parameter in parameters)


class WorkflowEngine:
    """Durable workflow engine with recoverable claims and explicit side-effect safety."""

    _CLAIM_LEASE_SECONDS = 300
    _TERMINAL_STATES = {
        WorkflowState.COMPLETED.value,
        WorkflowState.REJECTED.value,
        WorkflowState.CANCELLED.value,
    }

    def __init__(self, database: AtrinDatabase, adapters: Mapping[str, ActionAdapter] | None = None,
                 session_manager: Any | None = None):
        self.database = database
        self.adapters = dict(adapters or {})
        self.session_manager = session_manager
        self.recovery_engine = RecoveryEngine(checkpoint_store=self, workflow_controller=self, external_state_verifier=None)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _checkpoint(cls, connection: Any, workflow_id: str, payload: Mapping[str, Any]) -> int:
        checkpoint = dict(payload)
        checkpoint.setdefault("workflow_id", workflow_id)
        checkpoint.setdefault("checkpoint_version", 1)
        row = connection.execute("SELECT revision FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,)).fetchone()
        now = cls._now().isoformat()
        if row is None:
            revision = 1
            checkpoint["revision"] = revision
            connection.execute(
                "INSERT INTO workflow_checkpoints(workflow_id,checkpoint_version,revision,payload,updated_at) VALUES (?,?,?,?,?)",
                (workflow_id, int(checkpoint["checkpoint_version"]), revision,
                 json.dumps(checkpoint, separators=(",", ":"), sort_keys=True), now),
            )
            return revision
        current_revision = int(row["revision"])
        revision = current_revision + 1
        checkpoint["revision"] = revision
        cursor = connection.execute(
            "UPDATE workflow_checkpoints SET checkpoint_version=?, revision=?, payload=?, updated_at=? WHERE workflow_id=? AND revision=?",
            (int(checkpoint["checkpoint_version"]), revision,
             json.dumps(checkpoint, separators=(",", ":"), sort_keys=True), now, workflow_id, current_revision),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Checkpoint revision conflict; another worker updated the workflow")
        return revision

    @staticmethod
    def _load_in_connection(connection: Any, workflow_id: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT payload FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    @staticmethod
    def _parse_expiry(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _audit(self, connection: Any, workflow_id: str | None, event_type: str, actor: str,
               payload: Mapping[str, Any]) -> None:
        previous = connection.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = previous[0] if previous else ""
        canonical = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True)
        entry_hash = hashlib.sha256(f"{prev_hash}|{workflow_id or ''}|{event_type}|{actor}|{canonical}".encode()).hexdigest()
        connection.execute(
            "INSERT INTO audit_log(workflow_id,event_type,actor,payload,prev_hash,entry_hash) VALUES (?,?,?,?,?,?)",
            (workflow_id, event_type, actor, canonical, prev_hash, entry_hash),
        )

    def validate_audit_chain(self) -> bool:
        connection = self.database.get_connection()
        try:
            rows = connection.execute("SELECT workflow_id,event_type,actor,payload,prev_hash,entry_hash FROM audit_log ORDER BY seq").fetchall()
            previous = ""
            for row in rows:
                expected = hashlib.sha256(f"{previous}|{row['workflow_id'] or ''}|{row['event_type']}|{row['actor']}|{row['payload'] or '{}'}".encode()).hexdigest()
                if row["prev_hash"] != previous or row["entry_hash"] != expected:
                    return False
                previous = row["entry_hash"]
            return True
        finally:
            connection.close()

    async def save(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def load(self, workflow_id: str) -> dict[str, Any] | None:
        connection = self.database.get_connection()
        try:
            return self._load_in_connection(connection, workflow_id)
        finally:
            connection.close()

    def create_workflow(self, goal: str, plan: list[Task], client_request_id: str | None = None) -> str:
        if not goal.strip():
            raise ValueError("Workflow goal cannot be empty")
        if not plan:
            raise ValueError("Workflow must contain at least one task")
        if client_request_id is not None and (len(client_request_id) > 512 or not client_request_id.strip()):
            raise ValueError("client_request_id must be a non-empty value of at most 512 characters")
        task_ids = [task.task_id for task in plan]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task IDs must be unique")
        step_ids = [step.step_id for task in plan for step in task.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Step IDs must be unique")

        workflow_id = str(uuid.uuid4())
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if client_request_id:
                existing = connection.execute(
                    "SELECT workflow_id, goal FROM workflows WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if existing is not None:
                    if existing["goal"] != goal:
                        raise RuntimeError("client_request_id is already associated with a different workflow")
                    connection.commit()
                    return str(existing["workflow_id"])
            connection.execute(
                "INSERT INTO workflows(workflow_id,goal,state,client_request_id) VALUES (?,?,?,?)",
                (workflow_id, goal, WorkflowState.IDLE.value, client_request_id),
            )
            for task_index, task in enumerate(plan):
                task_status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
                if task_status != TaskStatus.PENDING.value:
                    raise ValueError("New workflows must start with PENDING tasks")
                connection.execute(
                    "INSERT INTO tasks(task_id,workflow_id,description,status,order_index) VALUES (?,?,?,?,?)",
                    (task.task_id, workflow_id, task.description, task_status, task_index),
                )
                for step_index, step in enumerate(task.steps):
                    status = step.status.value if isinstance(step.status, StepStatus) else str(step.status)
                    if status != StepStatus.PENDING.value:
                        raise ValueError("New workflows must start with PENDING steps")
                    key = step.idempotency_key or f"{workflow_id}:{step.step_id}"
                    operation_id = step.operation_id or str(uuid.uuid4())
                    connection.execute(
                        "INSERT INTO steps(step_id,task_id,action,provider_id,idempotency_key,operation_id,status,result,evidence,order_index,provider_profile_id,fencing_token,side_effecting) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (step.step_id, task.task_id, step.action, step.provider_id, key, operation_id, status,
                         step.result, step.evidence, step_index, step.provider_profile_id, step.fencing_token, int(bool(step.side_effecting))),
                    )
            self._checkpoint(connection, workflow_id, {
                "workflow_id": workflow_id, "state": WorkflowState.IDLE.value, "goal": goal,
                "plan_version": 1, "completed_tasks": [],
                "pending_tasks": [task.task_id for task in plan], "failed_tasks": [],
            })
            self._audit(connection, workflow_id, "WORKFLOW_CREATED", "workflow-engine",
                        {"goal": goal, "task_count": len(plan), "client_request_id": client_request_id})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return workflow_id

    def get_workflow_state(self, workflow_id: str) -> WorkflowState:
        connection = self.database.get_connection()
        try:
            row = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
            if row is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            return WorkflowState(row["state"])
        finally:
            connection.close()

    def _step(self, connection: Any, workflow_id: str, step_id: str) -> Any:
        row = connection.execute("""
            SELECT s.*, t.workflow_id, t.order_index AS task_order
            FROM steps s JOIN tasks t ON t.task_id=s.task_id
            WHERE s.step_id=? AND t.workflow_id=?
        """, (step_id, workflow_id)).fetchone()
        if row is None:
            raise LookupError(f"Step not found: {step_id}")
        return row

    def _assert_step_runnable(self, connection: Any, workflow_id: str, step: Any) -> None:
        workflow = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
        if workflow is None:
            raise LookupError(f"Workflow not found: {workflow_id}")
        if workflow["state"] in {WorkflowState.CANCELLED.value, WorkflowState.COMPLETED.value}:
            raise RuntimeError(f"Workflow is terminal: {workflow['state']}")
        previous_task = connection.execute(
            "SELECT task_id FROM tasks WHERE workflow_id=? AND order_index<? AND status!=? ORDER BY order_index LIMIT 1",
            (workflow_id, step["task_order"], TaskStatus.COMPLETED.value),
        ).fetchone()
        if previous_task is not None:
            raise RuntimeError(f"Previous task is not completed: {previous_task['task_id']}")
        previous_step = connection.execute(
            "SELECT step_id FROM steps WHERE task_id=? AND order_index<? AND status!=? ORDER BY order_index LIMIT 1",
            (step["task_id"], step["order_index"], StepStatus.CONFIRMED.value),
        ).fetchone()
        if previous_step is not None:
            raise RuntimeError(f"Previous step is not confirmed: {previous_step['step_id']}")

    async def _verify_existing_action(self, adapter: ActionAdapter, key: str, operation_id: str | None) -> str:
        kwargs = {"operation_id": operation_id} if _supports_keyword(adapter.verify_action, "operation_id") else {}
        return str(await _call(adapter.verify_action, key, **kwargs)).upper()

    async def _execute_action(self, adapter: ActionAdapter, action: str, key: str, operation_id: str,
                              fencing_token: int | None,
                              step_context: dict[str, Any] | None = None) -> Any:
        kwargs: dict[str, Any] = {}
        if _supports_keyword(adapter.execute, "operation_id"):
            kwargs["operation_id"] = operation_id
        if fencing_token is not None and _supports_keyword(adapter.execute, "fencing_token"):
            kwargs["fencing_token"] = fencing_token
        # FIX (بند ۱): pass step_context so adapters (A2A/MCP/ACP) can persist
        # the external task ID → durable recovery across restarts
        if step_context and _supports_keyword(adapter.execute, "step_context"):
            kwargs["step_context"] = step_context
        return await _call(adapter.execute, action, key, **kwargs)

    async def _cancel_action(self, adapter: ActionAdapter, key: str, operation_id: str | None) -> bool:
        method = getattr(adapter, "cancel", None)
        if not callable(method):
            return False
        kwargs = {"operation_id": operation_id} if _supports_keyword(method, "operation_id") else {}
        try:
            return bool(await _call(method, key, **kwargs))
        except Exception:
            return False

    async def _finalize_verified_action(self, workflow_id: str, step_id: str, key: str) -> Any:
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, step_id)
            ledger = connection.execute(
                "SELECT status FROM idempotency_ledger WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                (key, workflow_id, step_id),
            ).fetchone()
            if ledger is None:
                raise RuntimeError("Cannot finalize verified action without a durable execution record")
            connection.execute("UPDATE steps SET status=? WHERE step_id=?", (StepStatus.CONFIRMED.value, step_id))
            connection.execute("UPDATE idempotency_ledger SET status=?, confirmed_at=CURRENT_TIMESTAMP, expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                               (ExecutionStatus.CONFIRMED.value, key, workflow_id, step_id))
            connection.execute("UPDATE tasks SET status=? WHERE task_id=? AND NOT EXISTS (SELECT 1 FROM steps WHERE task_id=? AND status!=?)",
                               (TaskStatus.COMPLETED.value, step["task_id"], step["task_id"], StepStatus.CONFIRMED.value))
            remaining = connection.execute("SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!=?",
                                           (workflow_id, TaskStatus.COMPLETED.value)).fetchone()["n"]
            next_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (next_state.value, workflow_id))
            checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
            checkpoint.update({"step_id": step_id, "state": next_state.value, "action_idempotency_key": key,
                               "operation_id": step["operation_id"], "provider_id": step["provider_id"]})
            self._checkpoint(connection, workflow_id, checkpoint)
            self._audit(connection, workflow_id, "ACTION_CONFIRMED_BY_VERIFIER", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": key, "operation_id": step["operation_id"]})
            connection.commit()
            return {"result": step["result"], "evidence": step["evidence"]}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _mark_ambiguous(self, workflow_id: str, step_id: str, key: str, reason: str) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, step_id)
            connection.execute("UPDATE steps SET status=?, result=?, evidence=NULL WHERE step_id=? AND status IN (?, ?, ?)",
                               (StepStatus.AMBIGUOUS.value, reason, step_id, StepStatus.EXECUTING.value,
                                StepStatus.FAILED.value, StepStatus.PENDING.value))
            connection.execute("UPDATE idempotency_ledger SET status=?, expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                               (ExecutionStatus.AMBIGUOUS.value, key, workflow_id, step_id))
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=? AND state!=?",
                               (WorkflowState.WAITING_FOR_PROVIDER.value, workflow_id, WorkflowState.CANCELLED.value))
            checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
            checkpoint.update({"state": WorkflowState.WAITING_FOR_PROVIDER.value, "waiting_reason": reason,
                               "step_id": step_id, "action_idempotency_key": key, "operation_id": step["operation_id"]})
            self._checkpoint(connection, workflow_id, checkpoint)
            self._audit(connection, workflow_id, "ACTION_AMBIGUOUS", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": key, "operation_id": step["operation_id"], "reason": reason})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def execute_step(self, workflow_id: str, step_id: str) -> Any:
        connection = self.database.get_connection()
        verify_before_claim = False
        key: str
        adapter: ActionAdapter
        step: Any
        try:
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, step_id)
            registered_adapter = self.adapters.get(step["provider_id"])
            if registered_adapter is None:
                raise LookupError(f"No adapter registered for provider: {step['provider_id']}")
            adapter = registered_adapter
            key = step["idempotency_key"]
            operation_id = step["operation_id"]
            ledger = connection.execute("SELECT * FROM idempotency_ledger WHERE idempotency_key=?", (key,)).fetchone()
            if ledger and (ledger["workflow_id"] != workflow_id or ledger["step_id"] != step_id or ledger["provider_id"] != step["provider_id"]):
                raise RuntimeError(f"Idempotency key collision: {key} is already owned by another execution")
            if ledger and ledger["status"] == ExecutionStatus.CONFIRMED.value:
                existing = connection.execute("SELECT result,evidence FROM steps WHERE step_id=?", (step_id,)).fetchone()
                connection.commit()
                return {"result": existing["result"], "evidence": existing["evidence"]}
            self._assert_step_runnable(connection, workflow_id, step)
            if ledger and ledger["status"] == ExecutionStatus.IN_PROGRESS.value:
                expiry = self._parse_expiry(ledger["expires_at"])
                if expiry and expiry > self._now():
                    raise RuntimeError("Workflow step is already claimed by another execution")
                verify_before_claim = True
            elif ledger is not None:
                verify_before_claim = True
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        if verify_before_claim:
            verified = await self._verify_existing_action(adapter, key, operation_id)
            if verified == "CONFIRMED":
                return await self._finalize_verified_action(workflow_id, step_id, key)
            if verified not in {"NOT_STARTED", "FAILED"}:
                self._mark_ambiguous(workflow_id, step_id, key, f"Verifier returned {verified} while recovering operation")
                raise RuntimeError("External action state is ambiguous; workflow paused for recovery")

        claim_owner = str(uuid.uuid4())
        expires = (self._now() + timedelta(seconds=self._CLAIM_LEASE_SECONDS)).isoformat()
        side_effecting = bool(step["side_effecting"])
        fencing_token = step["fencing_token"]
        if side_effecting:
            if self.session_manager is None:
                raise PermissionError("Side-effecting steps require a SessionManager")
            profile_id = step["provider_profile_id"]
            if not profile_id:
                raise PermissionError("Side-effecting steps require provider_profile_id")
            if fencing_token is None:
                fencing_token = int(self.session_manager.acquire_lock(profile_id, workflow_id))
            elif not self.session_manager.validate_execution_lease(profile_id, workflow_id, int(fencing_token)):
                raise PermissionError("Execution lease is missing, expired, or fenced")

        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, step_id)
            ledger = connection.execute("SELECT * FROM idempotency_ledger WHERE idempotency_key=?", (step["idempotency_key"],)).fetchone()
            if ledger and (ledger["workflow_id"] != workflow_id or ledger["step_id"] != step_id or ledger["provider_id"] != step["provider_id"]):
                raise RuntimeError(f"Idempotency key collision: {step['idempotency_key']}")
            now = self._now()
            if ledger is None:
                connection.execute("INSERT INTO idempotency_ledger(idempotency_key,workflow_id,step_id,provider_id,operation_id,status,expires_at,claim_owner,attempt) VALUES (?,?,?,?,?,?,?,?,1)",
                                   (step["idempotency_key"], workflow_id, step_id, step["provider_id"], step["operation_id"], ExecutionStatus.IN_PROGRESS.value, expires, claim_owner))
            elif ledger["status"] in {"FAILED", ExecutionStatus.AMBIGUOUS.value, "PENDING"}:
                cursor = connection.execute("UPDATE idempotency_ledger SET status=?, operation_id=?, expires_at=?, claim_owner=?, attempt=attempt+1 WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND status IN ('FAILED','AMBIGUOUS','PENDING')",
                                            (ExecutionStatus.IN_PROGRESS.value, step["operation_id"], expires, claim_owner, step["idempotency_key"], workflow_id, step_id))
                if cursor.rowcount != 1:
                    raise RuntimeError("Workflow step is already claimed")
            elif ledger["status"] == ExecutionStatus.IN_PROGRESS.value:
                expiry = self._parse_expiry(ledger["expires_at"])
                if expiry and expiry > now:
                    raise RuntimeError("Workflow step is already claimed by another execution")
                if expiry is None or expiry > now:
                    raise RuntimeError("Workflow step has no reclaimable lease")
                verified = await self._verify_existing_action(adapter, step["idempotency_key"], step["operation_id"])
                if verified == "CONFIRMED":
                    connection.rollback()
                    return await self._finalize_verified_action(workflow_id, step_id, step["idempotency_key"])
                if verified not in {"NOT_STARTED", "FAILED"}:
                    connection.rollback()
                    self._mark_ambiguous(workflow_id, step_id, step["idempotency_key"], f"Verifier returned {verified} for expired claim")
                    raise RuntimeError("External action state is ambiguous; workflow paused for recovery")
                cursor = connection.execute("UPDATE idempotency_ledger SET status=?, operation_id=?, expires_at=?, claim_owner=?, attempt=attempt+1 WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND status=? AND expires_at<=?",
                                            (ExecutionStatus.IN_PROGRESS.value, step["operation_id"], expires, claim_owner, step["idempotency_key"], workflow_id, step_id, ExecutionStatus.IN_PROGRESS.value, now.isoformat()))
                if cursor.rowcount != 1:
                    raise RuntimeError("Expired workflow claim could not be reclaimed")
            else:
                raise RuntimeError(f"Unsupported idempotency state: {ledger['status']}")

            if fencing_token is not None:
                connection.execute("UPDATE steps SET fencing_token=?, operation_id=? WHERE step_id=?",
                                   (int(fencing_token), step["operation_id"], step_id))
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (WorkflowState.EXECUTING.value, workflow_id))
            connection.execute("UPDATE steps SET status=? WHERE step_id=?", (StepStatus.EXECUTING.value, step_id))
            connection.execute("UPDATE tasks SET status=? WHERE task_id=? AND status=?",
                               (TaskStatus.RUNNING.value, step["task_id"], TaskStatus.PENDING.value))
            self._checkpoint(connection, workflow_id, {
                "task_id": step["task_id"], "step_id": step_id, "state": WorkflowState.EXECUTING.value,
                "current_action": step["action"], "provider_id": step["provider_id"],
                "action_idempotency_key": step["idempotency_key"], "operation_id": step["operation_id"],
                "claim_owner": claim_owner, "fencing_token": fencing_token,
                "last_result": None, "evidence": None, "checkpoint_version": 1,
            })
            self._audit(connection, workflow_id, "ACTION_CLAIMED", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": step["idempotency_key"], "operation_id": step["operation_id"], "claim_owner": claim_owner})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        result_value: Any = None
        evidence: Any = None
        execute_error: Exception | None = None
        try:
            if side_effecting and self.session_manager is not None and not self.session_manager.validate_execution_lease(
                step["provider_profile_id"], workflow_id, int(fencing_token)
            ):
                raise PermissionError("Execution lease expired or was fenced before dispatch")
            result = await self._execute_action(
                adapter, step["action"], key, step["operation_id"], fencing_token,
                step_context={"workflow_id": workflow_id, "step_id": step_id,
                               "task_id": step["task_id"], "provider_id": step["provider_id"]},
            )
            evidence = result.get("evidence") if isinstance(result, dict) else None
            result_value = result.get("result", result) if isinstance(result, dict) else result
        except Exception as error:
            execute_error = error
            result_value = str(error)

        if execute_error is not None:
            self._mark_ambiguous(workflow_id, step_id, key, f"Dispatch outcome is ambiguous: {execute_error}")
            raise RuntimeError("External action result is ambiguous; workflow paused for recovery") from execute_error

        if side_effecting:
            try:
                verified = await self._verify_existing_action(adapter, key, step["operation_id"])
            except Exception as error:
                self._mark_ambiguous(workflow_id, step_id, key, f"Post-dispatch verification failed: {error}")
                raise RuntimeError("External action verification is ambiguous; workflow paused for recovery") from error
            if verified != "CONFIRMED":
                if verified == "FAILED":
                    self._mark_failed(workflow_id, step_id, key, str(result_value), evidence)
                    raise RuntimeError("External action was explicitly reported as failed")
                self._mark_ambiguous(workflow_id, step_id, key, f"Verifier returned {verified} after dispatch")
                raise RuntimeError("External action result is ambiguous; workflow paused for recovery")

        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
            claim = connection.execute("SELECT status, claim_owner FROM idempotency_ledger WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                                       (key, workflow_id, step_id)).fetchone()
            if not claim or claim["claim_owner"] != claim_owner or claim["status"] != ExecutionStatus.IN_PROGRESS.value:
                connection.rollback()
                return {"status": "STALE_WORKER", "result": result_value, "evidence": evidence}
            if current is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if current["state"] == WorkflowState.CANCELLED.value:
                connection.execute("UPDATE steps SET status=? WHERE step_id=? AND status=?",
                                   (StepStatus.CANCELLED.value, step_id, StepStatus.EXECUTING.value))
                connection.execute("UPDATE idempotency_ledger SET status=?, claim_owner=NULL, expires_at=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND claim_owner=?",
                                   (ExecutionStatus.CANCELLED.value, key, workflow_id, step_id, claim_owner))
                self._audit(connection, workflow_id, "ACTION_COMPLETED_AFTER_CANCEL", "workflow-engine",
                            {"step_id": step_id, "status": "CANCELLED"})
                connection.commit()
                raise RuntimeError("Workflow was cancelled while the external action was running")

            connection.execute("UPDATE steps SET status=?, result=?, evidence=? WHERE step_id=? AND status=?",
                               (StepStatus.CONFIRMED.value, str(result_value), evidence, step_id, StepStatus.EXECUTING.value))
            connection.execute("UPDATE idempotency_ledger SET status=?, confirmed_at=CURRENT_TIMESTAMP, expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND claim_owner=?",
                               (ExecutionStatus.CONFIRMED.value, key, workflow_id, step_id, claim_owner))
            task_counts = connection.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN status=? THEN 1 ELSE 0 END) AS done FROM steps WHERE task_id=?",
                                             (StepStatus.CONFIRMED.value, step["task_id"])).fetchone()
            if task_counts["total"] and task_counts["done"] == task_counts["total"]:
                connection.execute("UPDATE tasks SET status=? WHERE task_id=?", (TaskStatus.COMPLETED.value, step["task_id"]))
            remaining = connection.execute("SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!=?",
                                           (workflow_id, TaskStatus.COMPLETED.value)).fetchone()["n"]
            next_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
            self._audit(connection, workflow_id, "ACTION_CONFIRMED", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": key, "operation_id": step["operation_id"]})
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (next_state.value, workflow_id))
            checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
            checkpoint.update({"task_id": step["task_id"], "step_id": step_id, "state": next_state.value,
                               "current_action": step["action"], "provider_id": step["provider_id"],
                               "action_idempotency_key": key, "operation_id": step["operation_id"],
                               "last_result": str(result_value), "evidence": evidence})
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"result": result_value, "evidence": evidence}

    def _mark_failed(self, workflow_id: str, step_id: str, key: str, result: str, evidence: Any) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE steps SET status=?, result=?, evidence=? WHERE step_id=?",
                               (StepStatus.FAILED.value, result, evidence, step_id))
            connection.execute("UPDATE idempotency_ledger SET status='FAILED', expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                               (key, workflow_id, step_id))
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (WorkflowState.FAILED.value, workflow_id))
            self._checkpoint(connection, workflow_id, {"workflow_id": workflow_id, "step_id": step_id,
                                                       "state": WorkflowState.FAILED.value,
                                                       "action_idempotency_key": key, "last_result": result, "evidence": evidence})
            self._audit(connection, workflow_id, "ACTION_FAILED", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": key, "error": result})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def pause_and_checkpoint(self, workflow_id: str, reason: str, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        normalized = reason.lower()
        state = WorkflowState.WAITING_FOR_PROVIDER
        if "auth" in normalized or "login" in normalized:
            state = WorkflowState.WAITING_FOR_AUTH
        elif "network" in normalized or "connect" in normalized:
            state = WorkflowState.WAITING_FOR_NETWORK
        elif "approval" in normalized:
            state = WorkflowState.WAITING_FOR_HUMAN_APPROVAL
        elif "human" in normalized or "interaction" in normalized:
            state = WorkflowState.WAITING_FOR_HUMAN_INTERACTION
        persisted = dict(checkpoint)
        persisted.update({"workflow_id": workflow_id, "state": state.value, "waiting_reason": reason})
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
            if row is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if row["state"] == WorkflowState.CANCELLED.value:
                raise RuntimeError("Cannot pause a cancelled workflow")
            if row["state"] == WorkflowState.EXECUTING.value:
                raise RuntimeError("Cannot pause while an external action is executing")
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (state.value, workflow_id))
            self._checkpoint(connection, workflow_id, persisted)
            self._audit(connection, workflow_id, "WORKFLOW_PAUSED", "workflow-engine",
                        {"state": state.value, "reason": reason})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return persisted

    async def pause_workflow(self, workflow_id: str, reason: str) -> None:
        checkpoint = await self.load(workflow_id) or {"workflow_id": workflow_id}
        if "step_id" not in checkpoint:
            connection = self.database.get_connection()
            try:
                pending_step = connection.execute("""
                    SELECT s.step_id,s.task_id,s.action,s.provider_id,s.idempotency_key,s.operation_id,s.provider_profile_id,s.fencing_token
                    FROM steps s JOIN tasks t ON t.task_id=s.task_id
                    WHERE t.workflow_id=? AND s.status IN (?, ?, ?, ?)
                    ORDER BY t.order_index,s.order_index LIMIT 1
                """, (workflow_id, StepStatus.PENDING.value, StepStatus.EXECUTING.value,
                       StepStatus.FAILED.value, StepStatus.AMBIGUOUS.value)).fetchone()
            finally:
                connection.close()
            if pending_step is not None:
                checkpoint.update({"step_id": pending_step["step_id"], "task_id": pending_step["task_id"],
                                   "current_action": pending_step["action"], "provider_id": pending_step["provider_id"],
                                   "action_idempotency_key": pending_step["idempotency_key"], "operation_id": pending_step["operation_id"],
                                   "provider_profile_id": pending_step["provider_profile_id"], "fencing_token": pending_step["fencing_token"]})
        await self.pause_and_checkpoint(workflow_id, reason, checkpoint)

    async def resume_workflow(self, workflow_id: str, checkpoint: Mapping[str, Any] | None = None,
                              skip_action: bool = False) -> Any:
        if checkpoint is None:
            checkpoint = await self.load(workflow_id)
            if checkpoint is None:
                raise LookupError(f"No checkpoint found for workflow {workflow_id}")
            connection = self.database.get_connection()
            try:
                row = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
                if row is None:
                    raise LookupError(f"Workflow not found: {workflow_id}")
                if row["state"] == WorkflowState.CANCELLED.value:
                    raise RuntimeError("Cancelled workflows are terminal and cannot be resumed")
            finally:
                connection.close()
            provider_id = checkpoint.get("provider_id")
            if not provider_id:
                raise RuntimeError("Checkpoint does not identify a provider")
            adapter = self.adapters.get(provider_id)
            if adapter is None:
                raise LookupError(f"No adapter registered for provider: {provider_id}")
            recovery_engine = RecoveryEngine(checkpoint_store=self, workflow_controller=self, external_state_verifier=adapter)
            return await recovery_engine.resume_from_checkpoint(workflow_id)

        checkpoint = dict(checkpoint)
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workflow = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
            if workflow is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if workflow["state"] == WorkflowState.CANCELLED.value:
                raise RuntimeError("Cancelled workflows are terminal and cannot be resumed")
            step = self._step(connection, workflow_id, checkpoint.get("step_id", ""))
            if checkpoint.get("provider_id") not in (None, step["provider_id"]):
                raise ValueError("Checkpoint provider does not match the durable step")
            if checkpoint.get("action_idempotency_key") not in (None, step["idempotency_key"]):
                raise ValueError("Checkpoint idempotency key does not match the durable step")
            checkpoint.update({"provider_id": step["provider_id"], "action_idempotency_key": step["idempotency_key"], "operation_id": step["operation_id"]})
            if skip_action:
                ledger = connection.execute("SELECT status FROM idempotency_ledger WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                                            (step["idempotency_key"], workflow_id, step["step_id"])).fetchone()
                if ledger is None or ledger["status"] != ExecutionStatus.CONFIRMED.value:
                    raise RuntimeError("skip_action requires a durably confirmed execution")
                connection.execute("UPDATE steps SET status=? WHERE step_id=?", (StepStatus.CONFIRMED.value, step["step_id"]))
                connection.execute("UPDATE tasks SET status=? WHERE task_id=? AND NOT EXISTS (SELECT 1 FROM steps WHERE task_id=? AND status!=?)",
                                   (TaskStatus.COMPLETED.value, step["task_id"], step["task_id"], StepStatus.CONFIRMED.value))
                remaining = connection.execute("SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!=?",
                                               (workflow_id, TaskStatus.COMPLETED.value)).fetchone()["n"]
                final_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
                connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                                   (final_state.value, workflow_id))
                checkpoint["state"] = final_state.value
                self._checkpoint(connection, workflow_id, checkpoint)
                self._audit(connection, workflow_id, "RECOVERY_FINALIZED", "recovery-engine",
                            {"step_id": step["step_id"], "operation_id": step["operation_id"], "status": "CONFIRMED"})
                connection.commit()
                return checkpoint
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (WorkflowState.RECOVERING.value, workflow_id))
            checkpoint["state"] = WorkflowState.RECOVERING.value
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return await self.execute_step(workflow_id, checkpoint["step_id"])

    async def cancel_workflow(self, workflow_id: str) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workflow = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
            if workflow is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if workflow["state"] == WorkflowState.CANCELLED.value:
                connection.commit()
                return
            active = connection.execute("""
                SELECT s.step_id,s.idempotency_key,s.operation_id,s.provider_id,s.status
                FROM steps s JOIN tasks t ON t.task_id=s.task_id
                WHERE t.workflow_id=? AND s.status=?
                ORDER BY t.order_index,s.order_index LIMIT 1
            """, (workflow_id, StepStatus.EXECUTING.value)).fetchone()
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (WorkflowState.CANCELLING.value, workflow_id))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        cancel_confirmed = True
        if active is not None:
            adapter = self.adapters.get(active["provider_id"])
            cancel_confirmed = adapter is not None and await self._cancel_action(adapter, active["idempotency_key"], active["operation_id"])

        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
            if row is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if active is not None and not cancel_confirmed:
                connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                                   (WorkflowState.WAITING_FOR_PROVIDER.value, workflow_id))
                checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
                checkpoint.update({"state": WorkflowState.WAITING_FOR_PROVIDER.value,
                                   "waiting_reason": "Provider did not confirm cancellation",
                                   "step_id": active["step_id"], "operation_id": active["operation_id"]})
                self._checkpoint(connection, workflow_id, checkpoint)
                self._audit(connection, workflow_id, "CANCEL_UNCONFIRMED", "workflow-engine",
                            {"step_id": active["step_id"], "operation_id": active["operation_id"]})
                connection.commit()
                raise RuntimeError("Provider did not confirm cancellation; workflow remains in recovery")
            if active is not None:
                connection.execute("UPDATE steps SET status=? WHERE step_id=? AND status=?",
                                   (StepStatus.CANCELLED.value, active["step_id"], StepStatus.EXECUTING.value))
                connection.execute("UPDATE idempotency_ledger SET status=?, claim_owner=NULL, expires_at=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                                   (ExecutionStatus.CANCELLED.value, active["idempotency_key"], workflow_id, active["step_id"]))
            connection.execute("UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                               (WorkflowState.CANCELLED.value, workflow_id))
            checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
            checkpoint["state"] = WorkflowState.CANCELLED.value
            self._checkpoint(connection, workflow_id, checkpoint)
            self._audit(connection, workflow_id, "WORKFLOW_CANCELLED", "workflow-engine", {})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
