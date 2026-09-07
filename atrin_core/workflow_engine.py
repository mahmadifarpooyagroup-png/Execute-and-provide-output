"""Durable, vendor-neutral workflow orchestration."""

from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping, Protocol

from .database import AtrinDatabase
from .models import Step, Task, WorkflowState
from .recovery_engine import RecoveryEngine


class ActionAdapter(Protocol):
    async def execute(
        self,
        action: str,
        idempotency_key: str,
        *,
        fencing_token: int | None = None,
    ) -> Any: ...

    async def verify_action(self, idempotency_key: str) -> str: ...


async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
    result = method(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


class WorkflowEngine:
    """Vendor-neutral durable workflow engine with recoverable execution claims."""

    _CLAIM_LEASE_SECONDS = 300

    def __init__(self, database: AtrinDatabase, adapters: Mapping[str, ActionAdapter] | None = None,
                 session_manager: Any | None = None):
        self.database = database
        self.adapters = dict(adapters or {})
        self.session_manager = session_manager
        self.recovery_engine = RecoveryEngine(
            checkpoint_store=self,
            workflow_controller=self,
            external_state_verifier=None,
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _checkpoint(cls, connection: Any, workflow_id: str, payload: Mapping[str, Any]) -> int:
        checkpoint = dict(payload)
        checkpoint.setdefault("workflow_id", workflow_id)
        checkpoint.setdefault("checkpoint_version", 1)
        row = connection.execute(
            "SELECT revision FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        if row is None:
            revision = 1
            checkpoint["revision"] = revision
            connection.execute(
                "INSERT INTO workflow_checkpoints "
                "(workflow_id, checkpoint_version, revision, payload, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (workflow_id, checkpoint["checkpoint_version"], revision,
                 json.dumps(checkpoint, separators=(",", ":"), sort_keys=True), cls._now().isoformat()),
            )
            return revision

        current_revision = int(row["revision"])
        revision = current_revision + 1
        checkpoint["revision"] = revision
        cursor = connection.execute(
            "UPDATE workflow_checkpoints SET checkpoint_version=?, revision=?, payload=?, updated_at=? "
            "WHERE workflow_id=? AND revision=?",
            (checkpoint["checkpoint_version"], revision,
             json.dumps(checkpoint, separators=(",", ":"), sort_keys=True),
             cls._now().isoformat(), workflow_id, current_revision),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Checkpoint revision conflict; another worker updated the workflow")
        return revision

    @staticmethod
    def _load_in_connection(connection: Any, workflow_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT payload FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    @staticmethod
    def _parse_expiry(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _audit(self, connection: Any, workflow_id: str | None, event_type: str,
               actor: str, payload: Mapping[str, Any]) -> None:
        previous = connection.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = previous[0] if previous else ""
        canonical = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True)
        entry_hash = hashlib.sha256(
            f"{prev_hash}|{workflow_id or ''}|{event_type}|{actor}|{canonical}".encode()
        ).hexdigest()
        connection.execute(
            "INSERT INTO audit_log(workflow_id,event_type,actor,payload,prev_hash,entry_hash) "
            "VALUES (?,?,?,?,?,?)",
            (workflow_id, event_type, actor, canonical, prev_hash, entry_hash),
        )

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

    def create_workflow(self, goal: str, plan: list[Task]) -> str:
        workflow_id = str(uuid.uuid4())
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO workflows(workflow_id,goal,state) VALUES (?,?,?)",
                (workflow_id, goal, WorkflowState.IDLE.value),
            )
            for task_index, task in enumerate(plan):
                connection.execute(
                    "INSERT INTO tasks(task_id,workflow_id,description,status,order_index) VALUES (?,?,?,?,?)",
                    (task.task_id, workflow_id, task.description, task.status, task_index),
                )
                for step_index, step in enumerate(task.steps):
                    key = step.idempotency_key or str(uuid.uuid4())
                    connection.execute(
                        "INSERT INTO steps "
                        "(step_id,task_id,action,provider_id,idempotency_key,status,result,evidence,order_index,provider_profile_id,fencing_token) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (step.step_id, task.task_id, step.action, step.provider_id, key,
                         step.status, step.result, step.evidence, step_index,
                         step.provider_profile_id, step.fencing_token),
                    )
            self._checkpoint(connection, workflow_id, {
                "workflow_id": workflow_id,
                "state": WorkflowState.IDLE.value,
                "goal": goal,
                "plan_version": 1,
                "completed_tasks": [],
                "pending_tasks": [task.task_id for task in plan],
                "failed_tasks": [],
            })
            self._audit(connection, workflow_id, "WORKFLOW_CREATED", "workflow-engine",
                        {"goal": goal, "task_count": len(plan)})
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
            row = connection.execute(
                "SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
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
        workflow = connection.execute(
            "SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        if workflow is None:
            raise LookupError(f"Workflow not found: {workflow_id}")
        if workflow["state"] == WorkflowState.CANCELLED.value:
            raise RuntimeError("Workflow is cancelled")
        if workflow["state"] == WorkflowState.COMPLETED.value:
            raise RuntimeError("Workflow is already completed")

        previous_task = connection.execute("""
            SELECT task_id FROM tasks
            WHERE workflow_id=? AND order_index<? AND status!='COMPLETED'
            ORDER BY order_index LIMIT 1
        """, (workflow_id, step["task_order"])).fetchone()
        if previous_task is not None:
            raise RuntimeError(f"Previous task is not completed: {previous_task['task_id']}")

        previous_step = connection.execute("""
            SELECT step_id FROM steps
            WHERE task_id=? AND order_index<? AND status!='CONFIRMED'
            ORDER BY order_index LIMIT 1
        """, (step["task_id"], step["order_index"])).fetchone()
        if previous_step is not None:
            raise RuntimeError(f"Previous step is not confirmed: {previous_step['step_id']}")

    async def _verify_existing_action(self, adapter: ActionAdapter, key: str) -> str:
        return str(await _call(adapter.verify_action, key)).upper()

    async def _finalize_verified_action(self, workflow_id: str, step_id: str, key: str) -> Any:
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, step_id)
            connection.execute("UPDATE steps SET status='CONFIRMED' WHERE step_id=?", (step_id,))
            connection.execute(
                "UPDATE idempotency_ledger SET status='CONFIRMED', confirmed_at=CURRENT_TIMESTAMP, "
                "expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                (key, workflow_id, step_id),
            )
            connection.execute(
                "UPDATE tasks SET status='COMPLETED' WHERE task_id=? AND NOT EXISTS "
                "(SELECT 1 FROM steps WHERE task_id=? AND status!='CONFIRMED')",
                (step["task_id"], step["task_id"]),
            )
            remaining = connection.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!='COMPLETED'",
                (workflow_id,),
            ).fetchone()["n"]
            next_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (next_state.value, workflow_id),
            )
            checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
            checkpoint.update({"step_id": step_id, "state": next_state.value,
                               "action_idempotency_key": key, "provider_id": step["provider_id"]})
            self._checkpoint(connection, workflow_id, checkpoint)
            self._audit(connection, workflow_id, "ACTION_CONFIRMED_BY_VERIFIER", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": key})
            connection.commit()
            return {"result": step["result"], "evidence": step["evidence"]}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def execute_step(self, workflow_id: str, step_id: str) -> Any:
        connection = self.database.get_connection()
        verify_before_claim = False
        ledger_status = None
        key = None
        adapter: ActionAdapter
        step: Any
        try:
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, step_id)
            self._assert_step_runnable(connection, workflow_id, step)
            adapter = self.adapters.get(step["provider_id"])
            if adapter is None:
                raise LookupError(f"No adapter registered for provider: {step['provider_id']}")
            key = step["idempotency_key"]

            ledger = connection.execute(
                "SELECT * FROM idempotency_ledger WHERE idempotency_key=?", (key,)
            ).fetchone()
            if ledger and (
                ledger["workflow_id"] != workflow_id
                or ledger["step_id"] != step_id
                or ledger["provider_id"] != step["provider_id"]
            ):
                raise RuntimeError(f"Idempotency key collision: {key} is already owned by another execution")

            if ledger and ledger["status"] == "CONFIRMED":
                existing = connection.execute(
                    "SELECT result,evidence FROM steps WHERE step_id=?", (step_id,)
                ).fetchone()
                connection.commit()
                return {"result": existing["result"], "evidence": existing["evidence"]}

            ledger_status = ledger["status"] if ledger else None
            if ledger and ledger_status == "IN_PROGRESS":
                expiry = self._parse_expiry(ledger["expires_at"])
                if expiry and expiry > self._now():
                    connection.rollback()
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
            verified = await self._verify_existing_action(adapter, key)
            if verified == "CONFIRMED":
                return await self._finalize_verified_action(workflow_id, step_id, key)
            if verified not in {"NOT_STARTED", "FAILED"}:
                self._mark_ambiguous(workflow_id, step_id, key,
                                     f"Verifier returned {verified} while reclaiming execution")
                raise RuntimeError("External action state is ambiguous; workflow paused for recovery")

        claim_owner = str(uuid.uuid4())
        expires = (self._now() + timedelta(seconds=self._CLAIM_LEASE_SECONDS)).isoformat()
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, step_id)
            ledger = connection.execute(
                "SELECT * FROM idempotency_ledger WHERE idempotency_key=?", (step["idempotency_key"],)
            ).fetchone()
            if ledger and (
                ledger["workflow_id"] != workflow_id
                or ledger["step_id"] != step_id
                or ledger["provider_id"] != step["provider_id"]
            ):
                raise RuntimeError(f"Idempotency key collision: {step['idempotency_key']}")

            if ledger is None:
                connection.execute(
                    "INSERT INTO idempotency_ledger "
                    "(idempotency_key,workflow_id,step_id,provider_id,status,expires_at,claim_owner,attempt) "
                    "VALUES (?,?,?,?, 'IN_PROGRESS', ?, ?, 1)",
                    (step["idempotency_key"], workflow_id, step_id, step["provider_id"], expires, claim_owner),
                )
            elif ledger["status"] in {"FAILED", "AMBIGUOUS", "PENDING"}:
                cursor = connection.execute(
                    "UPDATE idempotency_ledger SET status='IN_PROGRESS', expires_at=?, claim_owner=?, attempt=attempt+1 "
                    "WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND status IN ('FAILED','AMBIGUOUS','PENDING')",
                    (expires, claim_owner, step["idempotency_key"], workflow_id, step_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Workflow step is already claimed")
            elif ledger["status"] == "IN_PROGRESS":
                expiry = self._parse_expiry(ledger["expires_at"])
                if expiry and expiry > self._now():
                    raise RuntimeError("Workflow step is already claimed by another execution")
                cursor = connection.execute(
                    "UPDATE idempotency_ledger SET status='IN_PROGRESS', expires_at=?, claim_owner=?, attempt=attempt+1 "
                    "WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND status='IN_PROGRESS' AND expires_at<=?",
                    (expires, claim_owner, step["idempotency_key"], workflow_id, step_id, self._now().isoformat()),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Expired workflow claim could not be reclaimed")
            else:
                raise RuntimeError(f"Unsupported idempotency state: {ledger['status']}")

            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (WorkflowState.EXECUTING.value, workflow_id),
            )
            connection.execute("UPDATE steps SET status='EXECUTING' WHERE step_id=?", (step_id,))
            self._checkpoint(connection, workflow_id, {
                "task_id": step["task_id"], "step_id": step_id,
                "state": WorkflowState.EXECUTING.value,
                "current_action": step["action"], "provider_id": step["provider_id"],
                "action_idempotency_key": step["idempotency_key"],
                "claim_owner": claim_owner, "last_result": None, "evidence": None,
                "checkpoint_version": 1,
            })
            self._audit(connection, workflow_id, "ACTION_CLAIMED", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": step["idempotency_key"],
                         "claim_owner": claim_owner})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        try:
            kwargs: dict[str, Any] = {}
            if step["fencing_token"] is not None:
                kwargs["fencing_token"] = step["fencing_token"]
                if self.session_manager is not None:
                    profile_id = step["provider_profile_id"]
                    if not profile_id or not self.session_manager.validate_execution_lease(
                        profile_id, workflow_id, int(step["fencing_token"])
                    ):
                        raise PermissionError("Execution lease is missing, expired, or fenced")
            try:
                result = await _call(adapter.execute, step["action"], key, **kwargs)
            except TypeError as error:
                if "fencing_token" in str(error) and kwargs:
                    # Preserve compatibility with legacy adapters while requiring
                    # callers that advertise fencing support to enforce it.
                    result = await _call(adapter.execute, step["action"], key)
                else:
                    raise
            evidence = result.get("evidence") if isinstance(result, dict) else None
            result_value = result.get("result", result) if isinstance(result, dict) else result
            status = "CONFIRMED"
        except Exception as error:
            result_value, evidence, status = str(error), None, "AMBIGUOUS"

        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            claim = connection.execute(
                "SELECT status, claim_owner FROM idempotency_ledger "
                "WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                (key, workflow_id, step_id),
            ).fetchone()
            if not claim or claim["claim_owner"] != claim_owner or claim["status"] != "IN_PROGRESS":
                connection.rollback()
                return {"status": "STALE_WORKER", "result": result_value, "evidence": evidence}

            if current is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if current["state"] == WorkflowState.CANCELLED.value:
                connection.execute(
                    "UPDATE steps SET status='CANCELLED' WHERE step_id=? AND status='EXECUTING'", (step_id,)
                )
                connection.execute(
                    "UPDATE idempotency_ledger SET status=?, claim_owner=NULL, expires_at=NULL "
                    "WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND claim_owner=?",
                    ("CONFIRMED" if status == "CONFIRMED" else "AMBIGUOUS", key, workflow_id, step_id, claim_owner),
                )
                self._audit(connection, workflow_id, "ACTION_COMPLETED_AFTER_CANCEL", "workflow-engine",
                            {"step_id": step_id, "status": status})
                connection.commit()
                raise RuntimeError("Workflow was cancelled while the external action was running")

            if status == "CONFIRMED":
                connection.execute(
                    "UPDATE steps SET status='CONFIRMED', result=?, evidence=? WHERE step_id=? AND status='EXECUTING'",
                    (str(result_value), evidence, step_id),
                )
                connection.execute(
                    "UPDATE idempotency_ledger SET status='CONFIRMED', confirmed_at=CURRENT_TIMESTAMP, "
                    "expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND claim_owner=?",
                    (key, workflow_id, step_id, claim_owner),
                )
                task_counts = connection.execute(
                    "SELECT COUNT(*) AS total, SUM(CASE WHEN status='CONFIRMED' THEN 1 ELSE 0 END) AS done "
                    "FROM steps WHERE task_id=?", (step["task_id"],)
                ).fetchone()
                if task_counts["total"] and task_counts["done"] == task_counts["total"]:
                    connection.execute("UPDATE tasks SET status='COMPLETED' WHERE task_id=?", (step["task_id"],))
                remaining = connection.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!='COMPLETED'", (workflow_id,)
                ).fetchone()["n"]
                next_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
                self._audit(connection, workflow_id, "ACTION_CONFIRMED", "workflow-engine",
                            {"step_id": step_id, "idempotency_key": key})
            else:
                connection.execute(
                    "UPDATE steps SET status='FAILED', result=?, evidence=? WHERE step_id=? AND status='EXECUTING'",
                    (str(result_value), evidence, step_id),
                )
                connection.execute(
                    "UPDATE idempotency_ledger SET status='AMBIGUOUS', expires_at=NULL, claim_owner=NULL "
                    "WHERE idempotency_key=? AND workflow_id=? AND step_id=? AND claim_owner=?",
                    (key, workflow_id, step_id, claim_owner),
                )
                next_state = WorkflowState.WAITING_FOR_PROVIDER
                self._audit(connection, workflow_id, "ACTION_AMBIGUOUS", "workflow-engine",
                            {"step_id": step_id, "idempotency_key": key, "error": str(result_value)})

            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (next_state.value, workflow_id),
            )
            checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
            checkpoint.update({
                "task_id": step["task_id"], "step_id": step_id, "state": next_state.value,
                "current_action": step["action"], "provider_id": step["provider_id"],
                "action_idempotency_key": key, "last_result": str(result_value), "evidence": evidence,
            })
            self._checkpoint(connection, workflow_id, checkpoint)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        if status == "AMBIGUOUS":
            raise RuntimeError("External action result is ambiguous; workflow paused for recovery")
        return result

    def _mark_ambiguous(self, workflow_id: str, step_id: str, key: str, reason: str) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE idempotency_ledger SET status='AMBIGUOUS', expires_at=NULL, claim_owner=NULL "
                "WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                (key, workflow_id, step_id),
            )
            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (WorkflowState.WAITING_FOR_PROVIDER.value, workflow_id),
            )
            checkpoint = self._load_in_connection(connection, workflow_id) or {"workflow_id": workflow_id}
            checkpoint.update({"state": WorkflowState.WAITING_FOR_PROVIDER.value, "waiting_reason": reason,
                               "step_id": step_id, "action_idempotency_key": key})
            self._checkpoint(connection, workflow_id, checkpoint)
            self._audit(connection, workflow_id, "ACTION_AMBIGUOUS", "workflow-engine",
                        {"step_id": step_id, "idempotency_key": key, "reason": reason})
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
                    SELECT s.step_id,s.task_id,s.action,s.provider_id,s.idempotency_key,
                           s.provider_profile_id,s.fencing_token
                    FROM steps s JOIN tasks t ON t.task_id=s.task_id
                    WHERE t.workflow_id=? AND s.status IN ('PENDING','EXECUTING','FAILED')
                    ORDER BY t.order_index,s.order_index LIMIT 1
                """, (workflow_id,)).fetchone()
            finally:
                connection.close()
            if pending_step is not None:
                checkpoint.update({"step_id": pending_step["step_id"], "task_id": pending_step["task_id"],
                                   "current_action": pending_step["action"], "provider_id": pending_step["provider_id"],
                                   "action_idempotency_key": pending_step["idempotency_key"],
                                   "provider_profile_id": pending_step["provider_profile_id"],
                                   "fencing_token": pending_step["fencing_token"]})
        await self.pause_and_checkpoint(workflow_id, reason, checkpoint)

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
            connection.execute("BEGIN IMMEDIATE")
            step = self._step(connection, workflow_id, checkpoint.get("step_id", ""))
            if checkpoint.get("provider_id") not in (None, step["provider_id"]):
                raise ValueError("Checkpoint provider does not match the durable step")
            if checkpoint.get("action_idempotency_key") not in (None, step["idempotency_key"]):
                raise ValueError("Checkpoint idempotency key does not match the durable step")
            checkpoint["provider_id"] = step["provider_id"]
            checkpoint["action_idempotency_key"] = step["idempotency_key"]

            if skip_action:
                connection.execute("UPDATE steps SET status='CONFIRMED' WHERE step_id=?", (step["step_id"],))
                connection.execute(
                    "UPDATE idempotency_ledger SET status='CONFIRMED', confirmed_at=CURRENT_TIMESTAMP, "
                    "expires_at=NULL, claim_owner=NULL WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                    (step["idempotency_key"], workflow_id, step["step_id"]),
                )
                connection.execute(
                    "UPDATE tasks SET status='COMPLETED' WHERE task_id=? AND NOT EXISTS "
                    "(SELECT 1 FROM steps WHERE task_id=? AND status!='CONFIRMED')",
                    (step["task_id"], step["task_id"]),
                )
                remaining = connection.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!='COMPLETED'", (workflow_id,)
                ).fetchone()["n"]
                final_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
                connection.execute(
                    "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                    (final_state.value, workflow_id),
                )
                checkpoint["state"] = final_state.value
                self._checkpoint(connection, workflow_id, checkpoint)
                self._audit(connection, workflow_id, "RECOVERY_FINALIZED", "recovery-engine",
                            {"step_id": step["step_id"], "status": "CONFIRMED"})
                connection.commit()
                return checkpoint

            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (WorkflowState.RECOVERING.value, workflow_id),
            )
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
            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (WorkflowState.CANCELLED.value, workflow_id),
            )
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
