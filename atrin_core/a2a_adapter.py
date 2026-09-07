from __future__ import annotations

import itertools
from typing import Any, Dict, Optional

import httpx

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
        if self._last_operation_key != idempotency_key or self._last_operation_id != operation_id or not self._last_task_id:
            return "AMBIGUOUS"
        status = self._last_task_status
        if status is None or status not in self.TERMINAL:
            try:
                result = await self.poll_task_status(self._last_task_id)
                status = str(result.get("status") or result.get("state") or "").lower()
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
