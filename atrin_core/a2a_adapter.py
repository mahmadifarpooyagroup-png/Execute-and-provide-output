from __future__ import annotations

import itertools
from typing import Any, Dict, Optional

import httpx
from typing import Optional as _Opt
from .external_op_store import ExternalOperationStore

from .interfaces import IProviderAdapter
from .protocol_models import A2AConfig, ProtocolConnection, ProtocolType


class A2AAdapter(IProviderAdapter):
    """A2A client adapter using JSON-RPC 2.0 message/task methods."""

    TERMINAL = {"completed", "succeeded", "failed", "rejected", "canceled", "cancelled"}

    def __init__(self, config: A2AConfig, *, client: Optional[httpx.AsyncClient] = None, timeout: float = 10.0) -> None:
        self.config = config
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.protocol_state = ProtocolConnection(protocol_type=ProtocolType.A2A, config=config, state="DISCOVERY", health="UNKNOWN")
        self.workflow_state = "IDLE"
        self.agent_card: Dict[str, Any] = {}
        self._request_ids = itertools.count(1)
        self._last_task_id: Optional[str] = None
        self._last_operation_key: Optional[str] = None
        self._last_operation_id: Optional[str] = None
        self._last_task_status: Optional[str] = None
        # Phase-A fix: durable external operation store (None = no persistence)
        self._store: _Opt[ExternalOperationStore] = None
        self._provider_id: str = "a2a"
        self._step_context: dict = {}

    async def discover_agent(self, agent_card_url: Optional[str] = None) -> Dict[str, Any]:
        response = await self._client.get(agent_card_url or self.config.agent_card_url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid A2A AgentCard response")
        self.agent_card = payload
        self.protocol_state.state = "DISCOVERED"
        self.protocol_state.health = "HEALTHY"
        return payload

    def _agent_url(self) -> str:
        return str(self.agent_card.get("url") or self.config.agent_card_url).rstrip("/")

    async def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        request_id = next(self._request_ids)
        response = await self._client.post(
            self._agent_url(),
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid A2A JSON-RPC response")
        if "error" in payload:
            raise RuntimeError(f"A2A {method} failed: {payload['error']}")
        result = payload.get("result", payload)
        return result if isinstance(result, dict) else {"result": result}

    async def send_task(self, task: Dict[str, Any], *, idempotency_key: Optional[str] = None,
                        operation_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.agent_card:
            await self.discover_agent()
        params = dict(task)
        message = params.get("message")
        if isinstance(message, dict):
            message = dict(message)
            metadata = dict(message.get("metadata") or {})
            if idempotency_key:
                metadata["atrin_idempotency_key"] = idempotency_key
            if operation_id:
                metadata["atrin_operation_id"] = operation_id
            if metadata:
                message["metadata"] = metadata
            params["message"] = message
        result = await self._rpc("message/send", params)
        self._last_task_id = result.get("id") or result.get("taskId") or result.get("task_id")
        self._last_operation_key = idempotency_key
        self._last_operation_id = operation_id
        self._last_task_status = str(result.get("status") or result.get("state") or "unknown").lower()
        # FIX (بند ۱۰): persist external task mapping for durable recovery after restart
        if self._store and idempotency_key and self._step_context:
            self._store.record(
                idempotency_key=idempotency_key,
                workflow_id=self._step_context.get("workflow_id", ""),
                step_id=self._step_context.get("step_id", ""),
                provider_id=self._provider_id,
                adapter_type="a2a",
                operation_id=operation_id,
                external_id=self._last_task_id,
                external_status=self._last_task_status,
            )
        self.protocol_state.state = "TASK_SENT"
        return result

    async def poll_task_status(self, task_id: str) -> Dict[str, Any]:
        result = await self._rpc("tasks/get", {"id": task_id})
        status = str(result.get("status") or result.get("state") or "unknown").lower()
        self._last_task_id = task_id
        self._last_task_status = status
        self.protocol_state.state = "TASK_DONE" if status in self.TERMINAL else "TASK_PENDING"
        self.protocol_state.health = "HEALTHY"
        return result

    async def execute(self, action: str, idempotency_key: str, *, operation_id: str | None = None,
                      fencing_token: int | None = None) -> Dict[str, Any]:
        return await self.send_task(
            {"message": {"role": "user", "parts": [{"kind": "text", "text": action}]}},
            idempotency_key=idempotency_key,
            operation_id=operation_id,
        )

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> str:
        # FIX (بند ۱۰): if in-memory cache is missing (e.g. after restart),
        # re-hydrate from the durable store before giving up with AMBIGUOUS.
        if (self._last_operation_key != idempotency_key or not self._last_task_id) and self._store:
            row = self._store.fetch(
                idempotency_key=idempotency_key,
                workflow_id=self._step_context.get("workflow_id", ""),
                step_id=self._step_context.get("step_id", ""),
            )
            if row and row["external_id"]:
                self._last_task_id = row["external_id"]
                self._last_operation_key = idempotency_key
                self._last_operation_id = row["operation_id"]
                self._last_task_status = row["external_status"]
        if self._last_operation_key != idempotency_key or self._last_operation_id != operation_id or not self._last_task_id:
            return "AMBIGUOUS"
        status = (self._last_task_status or "").lower()
        # FIX: external_status stored in DB uses our internal terms (CONFIRMED/FAILED)
        # Map them back to A2A protocol terms before TERMINAL comparison
        _INTERNAL_TO_A2A = {"confirmed": "completed", "failed": "failed", "ambiguous": "unknown"}
        status = _INTERNAL_TO_A2A.get(status, status)
        if status not in self.TERMINAL:
            try:
                result = await self.poll_task_status(self._last_task_id)
                # A2A response can be {"state": {"status": "completed"}} or {"status": "completed"}
                raw_state = result.get("state") or {}
                if isinstance(raw_state, dict):
                    status = str(raw_state.get("status") or result.get("status") or "").lower()
                else:
                    status = str(raw_state or result.get("status") or "").lower()
                self._last_task_status = status
            except Exception:
                return "AMBIGUOUS"
        if status in {"completed", "succeeded"}:
            return "CONFIRMED"
        if status in {"failed", "rejected", "canceled", "cancelled"}:
            return "FAILED"
        return "AMBIGUOUS"

    async def cancel(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        if self._last_operation_key != idempotency_key or self._last_operation_id != operation_id or not self._last_task_id:
            return False
        try:
            result = await self._rpc("tasks/cancel", {"id": self._last_task_id})
            status = str(result.get("status") or result.get("state") or "").lower()
            self._last_task_status = status
            return status in {"canceled", "cancelled"}
        except Exception:
            return False

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
