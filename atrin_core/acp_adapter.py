from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .interfaces import IProviderAdapter
from .protocol_models import ACPConfig, ProtocolConnection, ProtocolType


class ACPAdapter(IProviderAdapter):
    """ACP adapter for session-based agent integration.

    Atrin's durable workflow checkpoints remain independent of the ACP session
    lifecycle. ACP is treated as an integration primitive only.
    """

    def __init__(
        self,
        config: ACPConfig,
        *,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.protocol_state = ProtocolConnection(
            protocol_type=ProtocolType.ACP,
            config=config,
            state="IDLE",
            health="UNKNOWN",
        )
        self.workflow_state = "IDLE"
        self.session_id = config.session_id

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

    async def send_message(self, message: str) -> Dict[str, Any]:
        if not self.session_id:
            await self.start_session()
        payload = {"session_id": self.session_id, "message": message}
        response = await self._client.post(self._url("/message"), json=payload)
        response.raise_for_status()
        self.protocol_state.state = "RESPONDING"
        return response.json()

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

    async def verify_action(self, idempotency_key: str) -> str:
        if self.protocol_state.state in {"ACTIVE", "RESPONDING", "RESUMED"}:
            return "CONFIRMED"
        return "NOT_STARTED"
