from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .interfaces import IProviderAdapter
from .protocol_models import A2AConfig, ProtocolConnection, ProtocolType


class A2AAdapter(IProviderAdapter):
    """A2A adapter for agent card based discovery and task execution.

    Agent cards are used for discovery and metadata; Atrin workflow checkpoints are
    not coupled to the A2A task lifecycle.
    """

    def __init__(
        self,
        config: A2AConfig,
        *,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.protocol_state = ProtocolConnection(
            protocol_type=ProtocolType.A2A,
            config=config,
            state="DISCOVERY",
            health="UNKNOWN",
        )
        self.workflow_state = "IDLE"
        self.agent_card: Dict[str, Any] = {}

    async def discover_agent(self, agent_card_url: Optional[str] = None) -> Dict[str, Any]:
        url = agent_card_url or self.config.agent_card_url
        response = await self._client.get(url)
        response.raise_for_status()
        payload = response.json()
        self.agent_card = payload
        self.protocol_state.state = "DISCOVERED"
        self.protocol_state.health = "HEALTHY"
        return payload

    async def send_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        if not self.agent_card:
            await self.discover_agent()
        response = await self._client.post(self._agent_base_url() + "/tasks", json=task)
        response.raise_for_status()
        payload = response.json()
        self.protocol_state.state = "TASK_SENT"
        return payload

    async def poll_task_status(self, task_id: str) -> Dict[str, Any]:
        response = await self._client.get(self._agent_base_url() + f"/tasks/{task_id}")
        response.raise_for_status()
        payload = response.json()
        self.protocol_state.state = "TASK_PENDING" if payload.get("status") in {"pending", "running"} else "TASK_DONE"
        self.protocol_state.health = "HEALTHY"
        return payload

    async def verify_action(self, idempotency_key: str) -> str:
        if self.protocol_state.state in {"DISCOVERED", "TASK_SENT", "TASK_PENDING", "TASK_DONE"}:
            return "CONFIRMED"
        return "NOT_STARTED"

    def _agent_base_url(self) -> str:
        return self.config.agent_card_url.rsplit("/", 1)[0]
