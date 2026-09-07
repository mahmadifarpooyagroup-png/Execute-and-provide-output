"""Vendor-neutral workflow pause, checkpoint, and resume support."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .database import AtrinDatabase
from .models import ExecutionStatus, StepStatus, TaskStatus, WorkflowState


class CheckpointStore(Protocol):
    async def save(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> None: ...
    async def load(self, workflow_id: str) -> dict[str, Any] | None: ...


class WorkflowController(Protocol):
    async def pause_workflow(self, workflow_id: str, state: str) -> None: ...
    async def resume_workflow(self, workflow_id: str, checkpoint: Mapping[str, Any], skip_action: bool = False) -> Any: ...


class ExternalStateVerifier(Protocol):
    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> str: ...


@dataclass(frozen=True)
class ResumeResult:
    workflow_id: str
    status: str
    resumed: bool
    skipped_action: bool = False


class SQLiteCheckpointStore:
    """Durably stores complete checkpoint payloads with monotonic revisions."""

    def __init__(self, database: AtrinDatabase):
        self.database = database
        self._ensure_table()

    def _ensure_table(self) -> None:
        connection = self.database.get_connection()
        try:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    workflow_id TEXT PRIMARY KEY,
                    checkpoint_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.commit()
        finally:
            connection.close()

    async def save(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> None:
        payload = _sanitize_checkpoint(checkpoint)
        payload.setdefault("workflow_id", workflow_id)
        version = int(payload.get("checkpoint_version", 1))
        connection = self.database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT revision FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if existing is None:
                revision = 1
                payload["revision"] = revision
                connection.execute(
                    "INSERT INTO workflow_checkpoints(workflow_id,checkpoint_version,revision,payload,updated_at) VALUES (?,?,?,?,?)",
                    (workflow_id, version, revision, json.dumps(payload, separators=(",", ":"), sort_keys=True), now),
                )
            else:
                current = int(existing["revision"])
                revision = current + 1
                payload["revision"] = revision
                cursor = connection.execute(
                    "UPDATE workflow_checkpoints SET checkpoint_version=?, revision=?, payload=?, updated_at=? WHERE workflow_id=? AND revision=?",
                    (version, revision, json.dumps(payload, separators=(",", ":"), sort_keys=True), now, workflow_id, current),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Checkpoint revision conflict")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def load(self, workflow_id: str) -> dict[str, Any] | None:
        connection = self.database.get_connection()
        try:
            row = connection.execute(
                "SELECT payload FROM workflow_checkpoints WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            return json.loads(row["payload"]) if row else None
        finally:
            connection.close()


def _sanitize_checkpoint(value: Mapping[str, Any], depth: int = 0) -> dict[str, Any]:
    if depth > 12:
        raise ValueError("Checkpoint nesting is too deep")

    def sanitize(item: Any, level: int) -> Any:
        if level > 12:
            raise ValueError("Checkpoint nesting is too deep")
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, Mapping):
            return {str(key): sanitize(child, level + 1) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [sanitize(child, level + 1) for child in item]
        raise TypeError(f"Checkpoint contains unsupported value: {type(item).__name__}")

    return sanitize(value, depth)


async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
    result = method(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _supports_keyword(method: Any, name: str) -> bool:
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == name for parameter in parameters)


class RecoveryEngine:
    def __init__(self, checkpoint_store: CheckpointStore, workflow_controller: WorkflowController,
                 external_state_verifier: ExternalStateVerifier | None = None):
        self.checkpoint_store = checkpoint_store
        self.workflow_controller = workflow_controller
        self.external_state_verifier = external_state_verifier

    async def handle_network_unavailable(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        return await self._pause(workflow_id, checkpoint, WorkflowState.WAITING_FOR_NETWORK.value)

    async def handle_auth_required(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        return await self._pause(workflow_id, checkpoint, WorkflowState.WAITING_FOR_AUTH.value)

    async def _pause(self, workflow_id: str, checkpoint: Mapping[str, Any], state: str) -> dict[str, Any]:
        persisted = dict(checkpoint)
        persisted.update({"workflow_id": workflow_id, "state": state})
        atomic = getattr(self.workflow_controller, "pause_and_checkpoint", None)
        if atomic is not None:
            result = await _call(atomic, workflow_id, state, persisted)
            return dict(result) if isinstance(result, Mapping) else persisted
        await _call(self.workflow_controller.pause_workflow, workflow_id, state)
        await _call(self.checkpoint_store.save, workflow_id, persisted)
        return persisted

    def _finalize_verified_durable_operation(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> None:
        """Finalize a provider-confirmed operation without redispatching it."""
        database = getattr(self.workflow_controller, "database", None)
        if not isinstance(database, AtrinDatabase):
            raise RuntimeError("Durable workflow controller is required to finalize a verified operation")

        step_id = str(checkpoint.get("step_id") or "")
        key = str(checkpoint.get("action_idempotency_key") or "")
        if not step_id or not key:
            raise RuntimeError("Verified recovery checkpoint is missing step identity")

        connection = database.get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workflow = connection.execute(
                "SELECT state FROM workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            if workflow is None:
                raise LookupError(f"Workflow not found: {workflow_id}")
            if workflow["state"] == WorkflowState.CANCELLED.value:
                raise RuntimeError("Cancelled workflows are terminal and cannot be finalized")

            step = connection.execute("""
                SELECT s.*, t.workflow_id
                FROM steps s JOIN tasks t ON t.task_id=s.task_id
                WHERE s.step_id=? AND t.workflow_id=?
            """, (step_id, workflow_id)).fetchone()
            if step is None or step["idempotency_key"] != key:
                raise RuntimeError("Recovery checkpoint does not match the durable step")

            ledger = connection.execute(
                "SELECT status, operation_id FROM idempotency_ledger WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                (key, workflow_id, step_id),
            ).fetchone()
            if ledger is None:
                raise RuntimeError("Cannot finalize a verified action without a durable execution record")
            if ledger["operation_id"] not in (None, step["operation_id"]):
                raise RuntimeError("Execution operation identity does not match the durable step")

            connection.execute(
                "UPDATE steps SET status=? WHERE step_id=?",
                (StepStatus.CONFIRMED.value, step_id),
            )
            connection.execute(
                "UPDATE idempotency_ledger SET status=?, confirmed_at=CURRENT_TIMESTAMP, expires_at=NULL, claim_owner=NULL, operation_id=? WHERE idempotency_key=? AND workflow_id=? AND step_id=?",
                (ExecutionStatus.CONFIRMED.value, step["operation_id"], key, workflow_id, step_id),
            )
            connection.execute(
                "UPDATE tasks SET status=? WHERE task_id=? AND NOT EXISTS (SELECT 1 FROM steps WHERE task_id=? AND status!=?)",
                (TaskStatus.COMPLETED.value, step["task_id"], step["task_id"], StepStatus.CONFIRMED.value),
            )
            remaining = connection.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE workflow_id=? AND status!=?",
                (workflow_id, TaskStatus.COMPLETED.value),
            ).fetchone()["n"]
            final_state = WorkflowState.COMPLETED if remaining == 0 else WorkflowState.OBSERVING
            connection.execute(
                "UPDATE workflows SET state=?, updated_at=CURRENT_TIMESTAMP WHERE workflow_id=?",
                (final_state.value, workflow_id),
            )

            row = connection.execute(
                "SELECT revision, checkpoint_version FROM workflow_checkpoints WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()
            revision = int(row["revision"]) + 1 if row else 1
            payload = dict(checkpoint)
            payload.update({"workflow_id": workflow_id, "state": final_state.value,
                            "operation_id": step["operation_id"], "revision": revision})
            version = int(payload.get("checkpoint_version", row["checkpoint_version"] if row else 1))
            serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            if row:
                updated = connection.execute(
                    "UPDATE workflow_checkpoints SET checkpoint_version=?, revision=?, payload=?, updated_at=? WHERE workflow_id=? AND revision=?",
                    (version, revision, serialized, datetime.now(timezone.utc).isoformat(), workflow_id, int(row["revision"])),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("Checkpoint revision conflict while finalizing recovery")
            else:
                connection.execute(
                    "INSERT INTO workflow_checkpoints(workflow_id,checkpoint_version,revision,payload,updated_at) VALUES (?,?,?,?,?)",
                    (workflow_id, version, revision, serialized, datetime.now(timezone.utc).isoformat()),
                )

            audit = getattr(self.workflow_controller, "_audit", None)
            if callable(audit):
                audit(connection, workflow_id, "ACTION_CONFIRMED_BY_VERIFIER", "recovery-engine",
                      {"step_id": step_id, "operation_id": step["operation_id"], "status": "CONFIRMED"})
                audit(connection, workflow_id, "RECOVERY_FINALIZED", "recovery-engine",
                      {"step_id": step_id, "operation_id": step["operation_id"], "status": "CONFIRMED"})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def resume_from_checkpoint(self, workflow_id: str) -> ResumeResult:
        checkpoint = await _call(self.checkpoint_store.load, workflow_id)
        if checkpoint is None:
            raise LookupError(f"No checkpoint found for workflow {workflow_id}")

        action_key = checkpoint.get("action_idempotency_key")
        operation_id = checkpoint.get("operation_id")
        if action_key and self.external_state_verifier is None:
            raise RuntimeError("An external state verifier is required for side-effecting actions")

        status = "NOT_STARTED"
        if action_key:
            verifier = self.external_state_verifier.verify_action
            kwargs = {"operation_id": operation_id} if _supports_keyword(verifier, "operation_id") else {}
            status = str(await _call(verifier, action_key, **kwargs)).upper()

        if status == "CONFIRMED":
            self._finalize_verified_durable_operation(workflow_id, checkpoint)
            return ResumeResult(workflow_id, status, resumed=True, skipped_action=True)

        if status in {"FAILED", "NOT_STARTED"}:
            await _call(self.workflow_controller.resume_workflow, workflow_id, checkpoint)
            return ResumeResult(workflow_id, status, resumed=True)

        if status in {"AUTH_REQUIRED", "LOGIN_REQUIRED", "AUTH_CHALLENGE"}:
            await self._pause(workflow_id, checkpoint, WorkflowState.WAITING_FOR_AUTH.value)
            return ResumeResult(workflow_id, status, resumed=False)

        if status in {"NETWORK_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT"}:
            await self._pause(workflow_id, checkpoint, WorkflowState.WAITING_FOR_NETWORK.value)
            return ResumeResult(workflow_id, status, resumed=False)

        await self._pause(workflow_id, checkpoint, WorkflowState.WAITING_FOR_PROVIDER.value)
        return ResumeResult(workflow_id, status, resumed=False)
