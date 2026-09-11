from __future__ import annotations

import itertools
import json
from typing import Any, Dict, Optional

import httpx
from typing import Optional as _Opt
from .external_op_store import ExternalOperationStore

from .interfaces import IProviderAdapter
from .protocol_models import MCPConfig, ProtocolConnection, ProtocolType


class MCPAdapter(IProviderAdapter):
    """MCP Streamable HTTP adapter with explicit tool/argument semantics."""

    PROTOCOL_VERSION = "2026-07-28"

    def __init__(self, config: MCPConfig, *, client: Optional[httpx.AsyncClient] = None, timeout: float = 10.0) -> None:
        self.config = config
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.protocol_state = ProtocolConnection(protocol_type=ProtocolType.MCP, config=config, state="DISCONNECTED", health="UNKNOWN")
        self.workflow_state = "IDLE"
        self._connected = False
        self._request_ids = itertools.count(1)
        self._last_operation_key: Optional[str] = None
        self._last_operation_id: Optional[str] = None
        self._last_operation_result: Optional[Dict[str, Any]] = None
        # Phase-A fix: durable external operation store (None = no persistence)
        self._store: _Opt[ExternalOperationStore] = None
        self._provider_id: str = "mcp"
        self._step_context: dict = {}

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
        operation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not tool_name.strip():
            raise ValueError("MCP tool_name cannot be empty")
        await self._ensure_connected()
        response = await self._rpc("tools/call", params={"name": tool_name, "arguments": arguments}, name=tool_name)
        result = response.get("result", response)
        normalized = result if isinstance(result, dict) else {"result": result}
        normalized.setdefault("tool_name", tool_name)
        self._last_operation_key = idempotency_key
        self._last_operation_id = operation_id
        self._last_operation_result = normalized
        # FIX (بند ۹): persist tool call result for durable recovery
        if self._store and idempotency_key and self._step_context:
            self._store.record(
                idempotency_key=idempotency_key,
                workflow_id=self._step_context.get("workflow_id", ""),
                step_id=self._step_context.get("step_id", ""),
                provider_id=self._provider_id,
                adapter_type="mcp",
                operation_id=operation_id,
                external_id=normalized.get("id") or normalized.get("tool_use_id"),
                external_status="CONFIRMED",
            )
        return normalized

    def _resolve_tool_action(self, action: str) -> tuple[str, Dict[str, Any]]:
        raw = action.strip()
        if not raw:
            raise ValueError("MCP action cannot be empty")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict) and any(key in payload for key in ("tool", "tool_name", "name")):
            tool_name = payload.get("tool_name") or payload.get("tool") or payload.get("name")
            arguments = payload.get("arguments", payload.get("args", {}))
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise ValueError("MCP structured action requires a non-empty tool name")
            if not isinstance(arguments, dict):
                raise ValueError("MCP structured action arguments must be an object")
            return tool_name.strip(), arguments

        if self.config.default_tool:
            return self.config.default_tool, dict(self.config.default_arguments)

        return raw, {}

    async def execute(self, action: str, idempotency_key: str, *, operation_id: str | None = None,
                      fencing_token: int | None = None) -> Dict[str, Any]:
        tool_name, arguments = self._resolve_tool_action(action)
        return await self.call_tool(tool_name, arguments, idempotency_key=idempotency_key, operation_id=operation_id)

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> str:
        # FIX (بند ۹): re-hydrate from DB if memory cleared after restart
        if (self._last_operation_key != idempotency_key or self._last_operation_result is None) and self._store:
            row = self._store.fetch(
                idempotency_key=idempotency_key,
                workflow_id=self._step_context.get("workflow_id", ""),
                step_id=self._step_context.get("step_id", ""),
            )
            if row and row["external_status"] == "CONFIRMED":
                self._last_operation_key = idempotency_key
                self._last_operation_id = row["operation_id"]
                self._last_operation_result = {"external_id": row["external_id"]}
        if self._last_operation_key != idempotency_key or self._last_operation_id != operation_id:
            return "AMBIGUOUS"
        return "CONFIRMED" if self._last_operation_result is not None else "AMBIGUOUS"

    async def cancel(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        # MCP has no generic cancellation semantics that can safely be inferred
        # for arbitrary tools. Tool-specific cancellation must be implemented as
        # a provider capability rather than guessed here.
        return False

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
