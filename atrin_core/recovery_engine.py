"""Vendor-neutral workflow pause, checkpoint, and resume support."""

import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .database import AtrinDatabase
from .models import WorkflowState


class CheckpointStore(Protocol):
    async def save(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> None: ...
    async def load(self, workflow_id: str) -> dict[str, Any] | None: ...


class WorkflowController(Protocol):
    async def pause_workflow(self, workflow_id: str, state: str) -> None: ...
    async def resume_workflow(self, workflow_id: str, checkpoint: Mapping[str, Any], skip_action: bool = False) -> None: ...


class ExternalStateVerifier(Protocol):
    async def verify_action(self, idempotency_key: str) -> str: ...


@dataclass(frozen=True)
class ResumeResult:
    workflow_id: str
    status: str
    resumed: bool
    skipped_action: bool = False


class SQLiteCheckpointStore:
    """Durably stores the complete checkpoint payload without dropping extensions."""

    def __init__(self, database: AtrinDatabase):
        self.database = database
        self._ensure_table()

    def _ensure_table(self) -> None:
        connection = self.database.get_connection()
        connection.execute("""
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                workflow_id TEXT PRIMARY KEY,
                checkpoint_version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        connection.commit()
        connection.close()

    async def save(self, workflow_id: str, checkpoint: Mapping[str, Any]) -> None:
        payload = _sanitize_checkpoint(checkpoint)
        payload.setdefault("workflow_id", workflow_id)
        version = int(payload.get("checkpoint_version", 1))
        connection = self.database.get_connection()
        try:
            connection.execute("""
                INSERT INTO workflow_checkpoints (workflow_id, checkpoint_version, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    checkpoint_version = excluded.checkpoint_version,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
            """, (workflow_id, version, json.dumps(payload), datetime.now(timezone.utc).isoformat()))
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
        await _call(self.workflow_controller.pause_workflow, workflow_id, state)
        await _call(self.checkpoint_store.save, workflow_id, persisted)
        return persisted

    async def resume_from_checkpoint(self, workflow_id: str) -> ResumeResult:
        checkpoint = await _call(self.checkpoint_store.load, workflow_id)
        if checkpoint is None:
            raise LookupError(f"No checkpoint found for workflow {workflow_id}")

        action_key = checkpoint.get("action_idempotency_key")
        if action_key and self.external_state_verifier is None:
            raise RuntimeError("An external state verifier is required for side-effecting actions")

        status = "NOT_STARTED"
        if action_key:
            status = str(await _call(self.external_state_verifier.verify_action, action_key)).upper()

        if status == "CONFIRMED":
            await _call(self.workflow_controller.resume_workflow, workflow_id, checkpoint, skip_action=True)
            return ResumeResult(workflow_id, status, resumed=True, skipped_action=True)
        if status in {"FAILED", "NOT_STARTED"}:
            await _call(self.workflow_controller.resume_workflow, workflow_id, checkpoint)
            return ResumeResult(workflow_id, status, resumed=True)
        return ResumeResult(workflow_id, status, resumed=False)