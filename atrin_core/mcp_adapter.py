from __future__ import annotations

import itertools
from typing import Any, Dict, Optional

import httpx

from .interfaces import IProviderAdapter
from .protocol_models import MCPConfig, ProtocolConnection, ProtocolType


class MCPAdapter(IProviderAdapter):
    """MCP Streamable HTTP adapter for the stateless 2026-07-28 model."""

    PROTOCOL_VERSION = "2026-07-28"

    def __init__(
        self,
        config: MCPConfig,
        *,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.protocol_state = ProtocolConnection(
            protocol_type=ProtocolType.MCP,
            config=config,
            state="DISCONNECTED",
            health="UNKNOWN",
        )
        self.workflow_state = "IDLE"
        self._connected = False
        self._request_ids = itertools.count(1)
        self._last_operation_key: Optional[str] = None
        self._last_operation_result: Optional[Dict[str, Any]] = None

    def _url(self) -> str:
        return self.config.server_url.rstrip("/")

    def _headers(self, method: str, name: str | None = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self.PROTOCOL_VERSION,
            "Mcp-Method": method,
        }
        if name:
            headers["Mcp-Name"] = name
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        return headers

    async def connect(self) -> ProtocolConnection:
        # The 2026-07-28 stateless HTTP model does not require a session
        # handshake. Connection here is a local readiness state; the first
        # real MCP request performs the actual server availability check.
        self._connected = True
        self.protocol_state.state = "CONNECTED"
        self.protocol_state.health = "HEALTHY"
        return self.protocol_state

    async def list_tools(self) -> Dict[str, Any]:
        await self._ensure_connected()
        response = await self._rpc("tools/list", params={})
        result = response.get("result", response)
        return result if isinstance(result, dict) else {"tools": result}

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        await self._ensure_connected()
        response = await self._rpc(
            "tools/call",
            params={"name": tool_name, "arguments": arguments},
            name=tool_name,
        )
        result = response.get("result", response)
        normalized = result if isinstance(result, dict) else {"result": result}
        self._last_operation_key = idempotency_key
        self._last_operation_result = normalized
        return normalized

    async def execute(self, action: str, idempotency_key: str, *, fencing_token: int | None = None) -> Dict[str, Any]:
        return await self.call_tool(action, {}, idempotency_key=idempotency_key)

    async def verify_action(self, idempotency_key: str) -> str:
        if self._last_operation_key != idempotency_key:
            return "AMBIGUOUS"
        return "CONFIRMED" if self._last_operation_result is not None else "AMBIGUOUS"

    async def disconnect(self) -> None:
        self._connected = False
        self.protocol_state.state = "DISCONNECTED"
        self.protocol_state.health = "OFFLINE"
        if self._owns_client:
            await self._client.aclose()

    async def _rpc(self, method: str, *, params: Dict[str, Any], name: str | None = None) -> Dict[str, Any]:
        request_id = next(self._request_ids)
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        response = await self._client.post(self._url(), json=payload, headers=self._headers(method, name))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid MCP JSON-RPC response")
        if "error" in data:
            raise RuntimeError(f"MCP {method} failed: {data['error']}")
        return data

    async def _ensure_connected(self) -> None:
        if not self._connected:
            await self.connect()
