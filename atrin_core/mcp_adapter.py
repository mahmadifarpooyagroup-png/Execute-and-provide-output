from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .interfaces import IProviderAdapter
from .protocol_models import MCPConfig, ProtocolConnection, ProtocolType


class MCPAdapter(IProviderAdapter):
    """MCP protocol adapter for tool/resource access.

    The workflow engine remains vendor-neutral and does not depend on MCP lifecycle
    state. MCP is treated as a tool/resource integration layer only.
    """

    def __init__(
        self,
        config: MCPConfig,
        *,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.protocol_state = ProtocolConnection(
            protocol_type=ProtocolType.MCP,
            config=config,
            state="DISCONNECTED",
            health="UNKNOWN",
        )
        self.workflow_state = "IDLE"
        self._connected = False

    def _url(self, suffix: str) -> str:
        base = self.config.server_url.rstrip("/")
        if suffix.startswith("http://") or suffix.startswith("https://"):
            return suffix
        return f"{base}{suffix if suffix.startswith('/') else '/' + suffix}"

    async def connect(self) -> ProtocolConnection:
        headers = {"Content-Type": "application/json"}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {"tools": True, "resources": True},
                "clientInfo": {"name": "atrin-core", "version": "0.1.0"},
            },
        }
        response = await self._client.post(self._url("/mcp"), json=payload, headers=headers)
        response.raise_for_status()
        self._connected = True
        self.protocol_state.state = "CONNECTED"
        self.protocol_state.health = "HEALTHY"
        return self.protocol_state

    async def list_tools(self) -> Dict[str, Any]:
        await self._ensure_connected()
        response = await self._client.get(self._url("/mcp/tools"))
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"tools": payload}

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_connected()
        response = await self._client.post(
            self._url("/mcp/call"),
            json={"tool": tool_name, "arguments": arguments},
        )
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict):
            return result
        return {"result": result}

    async def disconnect(self) -> None:
        if not self._connected:
            return
        try:
            await self._client.post(self._url("/mcp/disconnect"), json={})
        except Exception:
            pass
        self._connected = False
        self.protocol_state.state = "DISCONNECTED"
        self.protocol_state.health = "OFFLINE"

    async def verify_action(self, idempotency_key: str) -> str:
        if self._connected and self.protocol_state.state == "CONNECTED":
            return "CONFIRMED"
        return "NOT_STARTED"

    async def _ensure_connected(self) -> None:
        if self._connected:
            return
        await self.connect()
