from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .interfaces import IProviderAdapter
from .protocol_models import ACPConfig, ProtocolConnection, ProtocolType


class ACPAdapter(IProviderAdapter):
    """ACP adapter for session-based agent integration."""

    def __init__(self, config: ACPConfig, *, client: Optional[httpx.AsyncClient] = None, timeout: float = 10.0) -> None:
        self.config = config
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.protocol_state = ProtocolConnection(protocol_type=ProtocolType.ACP, config=config, state="IDLE", health="UNKNOWN")
        self.workflow_state = "IDLE"
        self.session_id = config.session_id
        self._last_operation_key: Optional[str] = None
        self._last_operation_id: Optional[str] = None
        self._last_result: Optional[Dict[str, Any]] = None

    def _url(self, suffix: str) -> str:
        base = self.config.agent_path.rstrip("/")
        if suffix.startswith("http://") or suffix.startswith("https://"):
            return suffix
        return f"{base}{suffix if suffix.startswith('/') else '/' + suffix}"

    async def start_session(self) -> Dict[str, Any]:
        response = await self._client.post(self._url("/session"), json={"resume": self.config.resume_supported})
        response.raise_for_status()
        payload = response.json()
        self.session_id = payload.get("session_id") or payload.get("id") or self.session_id
        self.config.session_id = self.session_id
        self.protocol_state.state = "ACTIVE"
        self.protocol_state.health = "HEALTHY"
        return payload

    async def send_message(self, message: str, *, idempotency_key: Optional[str] = None,
                           operation_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.session_id:
            await self.start_session()
        payload = {"session_id": self.session_id, "message": message}
        metadata: dict[str, str] = {}
        if idempotency_key:
            metadata["atrin_idempotency_key"] = idempotency_key
        if operation_id:
            metadata["atrin_operation_id"] = operation_id
        if metadata:
            payload["metadata"] = metadata
        response = await self._client.post(self._url("/message"), json=payload)
        response.raise_for_status()
        result = response.json()
        self._last_operation_key = idempotency_key
        self._last_operation_id = operation_id
        self._last_result = result if isinstance(result, dict) else {"result": result}
        self.protocol_state.state = "RESPONDING"
        return self._last_result

    async def execute(self, action: str, idempotency_key: str, *, operation_id: str | None = None,
                      fencing_token: int | None = None) -> Dict[str, Any]:
        return await self.send_message(action, idempotency_key=idempotency_key, operation_id=operation_id)

    async def resume_session(self, session_id: str) -> Dict[str, Any]:
        self.session_id = session_id
        self.config.session_id = session_id
        response = await self._client.get(self._url(f"/session/{session_id}"))
        response.raise_for_status()
        self.protocol_state.state = "RESUMED"
        self.protocol_state.health = "HEALTHY"
        return response.json()

    async def close_session(self) -> None:
        if not self.session_id:
            return
        response = await self._client.delete(self._url(f"/session/{self.session_id}"))
        response.raise_for_status()
        self.protocol_state.state = "CLOSED"
        self.protocol_state.health = "OFFLINE"
        self.session_id = None
        self.config.session_id = None

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> str:
        if self._last_operation_key != idempotency_key or self._last_operation_id != operation_id or self._last_result is None:
            return "AMBIGUOUS"
        return "CONFIRMED"

    async def cancel(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        # ACP cancellation semantics vary by implementation; a generic adapter
        # must not invent a cancellation operation. Provider-specific subclasses
        # can override this safely.
        return False

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
