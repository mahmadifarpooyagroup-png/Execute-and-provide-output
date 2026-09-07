from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import httpx

from .a2a_adapter import A2AAdapter
from .acp_adapter import ACPAdapter
from .interfaces import IProviderAdapter
from .mcp_adapter import MCPAdapter
from .models import Provider
from .protocol_models import A2AConfig, ACPConfig, MCPConfig
from .provider_strategy import ConfigurableWebStrategy
from .web_adapter import BrowserMode, GenericWebAdapter


AdapterFactory = Callable[[Provider, Optional[str]], IProviderAdapter]


class CompatibleChatAdapter(IProviderAdapter):
    """Generic chat-completions HTTP adapter with no vendor-specific assumptions."""

    def __init__(self, provider: Provider, *, timeout: float = 60.0) -> None:
        config = dict(provider.metadata.get("api") or {})
        self.base_url = str(config.get("base_url") or provider.endpoint or "").rstrip("/")
        if not self.base_url:
            raise ValueError(f"Provider {provider.id} requires metadata.api.base_url or endpoint")
        self.chat_path = str(config.get("chat_path") or "/chat/completions")
        self.model = str(config.get("model") or "")
        if not self.model:
            raise ValueError(f"Provider {provider.id} requires metadata.api.model")
        self.api_key_env = str(config.get("api_key_env") or "")
        if not self.api_key_env:
            raise ValueError(f"Provider {provider.id} requires metadata.api.api_key_env")
        self.idempotency_header = str(config.get("idempotency_header") or "").strip()
        self.extra_body = dict(config.get("extra_body") or {})
        self.extra_headers = {str(k): str(v) for k, v in dict(config.get("headers") or {}).items()}
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
        self._last_operation_key: str | None = None
        self._last_operation_id: str | None = None
        self._last_result: dict[str, Any] | None = None

    def _api_key(self) -> str:
        value = os.getenv(self.api_key_env, "")
        if not value:
            raise RuntimeError(f"API credential environment variable is not set: {self.api_key_env}")
        return value

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        if self.idempotency_header and idempotency_key:
            headers[self.idempotency_header] = idempotency_key
        return headers

    async def execute(
        self,
        action: str,
        idempotency_key: str,
        *,
        operation_id: str | None = None,
        fencing_token: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": action}],
            **self.extra_body,
        }
        if fencing_token is not None and "fencing_token" not in payload:
            payload["fencing_token"] = fencing_token
        response = await self._client.post(
            f"{self.base_url}{self.chat_path}",
            json=payload,
            headers=self._headers(idempotency_key),
        )
        response.raise_for_status()
        data = response.json()
        result = self._extract_text(data)
        normalized = {"result": result, "response": data, "operation_id": operation_id}
        self._last_operation_key = idempotency_key
        self._last_operation_id = operation_id
        self._last_result = normalized
        return normalized

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> str:
        if self._last_operation_key == idempotency_key and self._last_operation_id == operation_id and self._last_result is not None:
            return "CONFIRMED"
        return "AMBIGUOUS"

    def capabilities(self) -> set[str]:
        return {"chat", "text", "api"}

    async def health(self) -> str:
        try:
            response = await self._client.get(self.base_url, headers=self._headers())
            return "HEALTHY" if response.is_success else "DEGRADED"
        except Exception:
            return "OFFLINE"

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _extract_text(data: Any) -> str:
        if isinstance(data, dict):
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        return message["content"]
                    if isinstance(first.get("text"), str):
                        return first["text"]
            if isinstance(data.get("output_text"), str):
                return data["output_text"]
            if isinstance(data.get("result"), str):
                return data["result"]
        return json.dumps(data, ensure_ascii=False, sort_keys=True)


class _ProfileAwareAdapter(IProviderAdapter):
    """Resolve an adapter against the profile attached to a durable operation."""

    def __init__(self, provider: Provider, database: Any, factory: AdapterFactory) -> None:
        self.provider = provider
        self.database = database
        self.factory = factory
        self._adapters: dict[str, IProviderAdapter] = {}

    def _profile_id(self, idempotency_key: str, operation_id: str | None) -> str | None:
        connection = self.database.get_connection()
        try:
            if operation_id:
                row = connection.execute(
                    "SELECT provider_profile_id FROM steps WHERE provider_id=? AND operation_id=? LIMIT 1",
                    (self.provider.id, operation_id),
                ).fetchone()
                if row and row[0]:
                    return str(row[0])
            row = connection.execute(
                "SELECT provider_profile_id FROM steps WHERE provider_id=? AND idempotency_key=? LIMIT 1",
                (self.provider.id, idempotency_key),
            ).fetchone()
            return str(row[0]) if row and row[0] else None
        finally:
            connection.close()

    async def _adapter(self, idempotency_key: str, operation_id: str | None) -> IProviderAdapter:
        profile_id = self._profile_id(idempotency_key, operation_id) or "default"
        if profile_id not in self._adapters:
            self._adapters[profile_id] = self.factory(self.provider, profile_id)
        return self._adapters[profile_id]

    async def execute(self, action: str, idempotency_key: str, *, operation_id: str | None = None, fencing_token: int | None = None) -> Any:
        adapter = await self._adapter(idempotency_key, operation_id)
        return await adapter.execute(action, idempotency_key, operation_id=operation_id, fencing_token=fencing_token)

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> str:
        adapter = await self._adapter(idempotency_key, operation_id)
        return await adapter.verify_action(idempotency_key, operation_id=operation_id)

    async def cancel(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        adapter = await self._adapter(idempotency_key, operation_id)
        method = getattr(adapter, "cancel", None)
        if callable(method):
            return bool(await method(idempotency_key, operation_id=operation_id))
        method = getattr(adapter, "cancel_action", None)
        if callable(method):
            return bool(await method(idempotency_key, operation_id=operation_id))
        return False

    async def health(self) -> str:
        statuses: list[str] = []
        for adapter in self._adapters.values():
            health = getattr(adapter, "health", None)
            if callable(health):
                statuses.append(str(await health()).upper())
        if "HEALTHY" in statuses:
            return "HEALTHY"
        return statuses[0] if statuses else "UNKNOWN"

    def capabilities(self) -> set[str]:
        configured = self.provider.metadata.get("capabilities") or []
        return ProviderAdapterRegistry.normalize_capabilities(configured)

    async def close(self) -> None:
        for adapter in self._adapters.values():
            close = getattr(adapter, "close", None)
            if callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
        self._adapters.clear()


class ProviderAdapterRegistry:
    """Configuration-driven registry for vendor-neutral provider adapters."""

    _FACTORIES: dict[str, AdapterFactory] = {}

    def __init__(self) -> None:
        self.providers: dict[str, Provider] = {}

    @staticmethod
    def normalize_capabilities(value: Any) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            return {value.strip().lower()} if value.strip() else set()
        if isinstance(value, (list, tuple, set, frozenset)):
            return {str(item).strip().lower() for item in value if str(item).strip()}
        raise ValueError("Provider capabilities must be a string or sequence of strings")

    @classmethod
    def register_factory(cls, adapter_id: str, factory: AdapterFactory) -> None:
        normalized = adapter_id.strip().lower()
        if not normalized:
            raise ValueError("adapter_id cannot be empty")
        cls._FACTORIES[normalized] = factory

    def register(self, config: Mapping[str, Any] | Provider) -> Provider:
        provider = config if isinstance(config, Provider) else Provider.from_config(dict(config))
        if not provider.id.strip():
            raise ValueError("Provider id cannot be empty")
        self.normalize_capabilities(provider.metadata.get("capabilities"))
        if not provider.enabled:
            self.providers[provider.id] = provider
            return provider
        if provider.adapter_id.lower() not in self._FACTORIES:
            raise ValueError(f"Unsupported provider adapter: {provider.adapter_id}")
        self.providers[provider.id] = provider
        return provider

    def get(self, provider_id: str) -> Provider:
        try:
            return self.providers[provider_id]
        except KeyError as error:
            raise KeyError(f"Provider is not registered: {provider_id}") from error

    def catalog(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for provider in sorted(self.providers.values(), key=lambda item: (item.priority, item.name, item.id)):
            capabilities = self.normalize_capabilities(provider.metadata.get("capabilities"))
            if provider.adapter_id.lower() in {"api", "chat-completions"}:
                capabilities.update({"chat", "text", "api"})
            elif provider.adapter_id.lower() in {"web", "generic-web"}:
                capabilities.update({"web", "browser"})
            items.append({
                "id": provider.id,
                "name": provider.name,
                "description": provider.description,
                "connection_kind": provider.connection_kind.value,
                "transport": provider.transport,
                "adapter_id": provider.adapter_id,
                "protocol": provider.protocol,
                "capabilities": sorted(capabilities),
                "enabled": provider.enabled,
                "health_status": provider.health_status,
                "version": provider.version,
            })
        return items

    def build_adapters(self, database: Any) -> dict[str, IProviderAdapter]:
        adapters: dict[str, IProviderAdapter] = {}
        for provider in self.providers.values():
            if provider.enabled:
                factory = self._FACTORIES.get(provider.adapter_id.lower())
                if factory is not None:
                    adapters[provider.id] = _ProfileAwareAdapter(provider, database, factory)
        return adapters

    @classmethod
    def from_environment(cls, env_name: str = "ATRIN_PROVIDERS_JSON") -> "ProviderAdapterRegistry":
        registry = cls()
        raw = os.getenv(env_name, "")
        if not raw:
            file_path = os.getenv("ATRIN_PROVIDERS_FILE", "")
            if file_path:
                path = Path(file_path).expanduser()
                if not path.is_file():
                    raise FileNotFoundError(f"Provider configuration file not found: {path}")
                if path.stat().st_size > 1_048_576:
                    raise ValueError("Provider configuration file is too large")
                raw = path.read_text(encoding="utf-8")
        if not raw:
            return registry
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Provider configuration must be a JSON array")
        for item in payload:
            if not isinstance(item, Mapping):
                raise ValueError("Each provider configuration must be an object")
            registry.register(item)
        return registry


def _web_factory(provider: Provider, profile_id: Optional[str]) -> IProviderAdapter:
    web_config = dict(provider.metadata.get("web") or {})
    return GenericWebAdapter(
        provider.id,
        profile_id or "default",
        lambda page: ConfigurableWebStrategy(page, web_config),
        mode=BrowserMode(str(web_config.get("mode", BrowserMode.MANAGED_NEW_BROWSER.value))),
        start_url=web_config.get("start_url") or provider.endpoint,
        profile_path=web_config.get("profile_path"),
        browser_name=str(web_config.get("browser_name", "chromium")),
        headless=bool(web_config.get("headless", True)),
        cdp_endpoint=web_config.get("cdp_endpoint"),
        allow_cdp_attach=bool(web_config.get("allow_cdp_attach", False)),
        completion_timeout=float(web_config.get("completion_timeout", 30.0)),
    )


def _api_factory(provider: Provider, profile_id: Optional[str]) -> IProviderAdapter:
    return CompatibleChatAdapter(provider)


def _mcp_factory(provider: Provider, profile_id: Optional[str]) -> IProviderAdapter:
    config = dict(provider.metadata.get("mcp") or {})
    auth_env = config.get("auth_token_env")
    auth_token = os.getenv(str(auth_env)) if auth_env else config.get("auth_token")
    return MCPAdapter(MCPConfig(server_url=str(config.get("server_url") or provider.endpoint),
                                transport=str(config.get("transport", "streamable-http")),
                                capabilities=list(config.get("capabilities") or []), auth_token=auth_token))


def _a2a_factory(provider: Provider, profile_id: Optional[str]) -> IProviderAdapter:
    config = dict(provider.metadata.get("a2a") or {})
    return A2AAdapter(A2AConfig(agent_card_url=str(config.get("agent_card_url") or provider.endpoint),
                                capabilities=list(config.get("capabilities") or []), auth_method=config.get("auth_method")))


def _acp_factory(provider: Provider, profile_id: Optional[str]) -> IProviderAdapter:
    config = dict(provider.metadata.get("acp") or {})
    return ACPAdapter(ACPConfig(agent_path=str(config.get("agent_path") or provider.endpoint),
                                session_id=config.get("session_id"), resume_supported=bool(config.get("resume_supported", False))))


ProviderAdapterRegistry.register_factory("web", _web_factory)
ProviderAdapterRegistry.register_factory("generic-web", _web_factory)
ProviderAdapterRegistry.register_factory("api", _api_factory)
ProviderAdapterRegistry.register_factory("chat-completions", _api_factory)
ProviderAdapterRegistry.register_factory("mcp", _mcp_factory)
ProviderAdapterRegistry.register_factory("a2a", _a2a_factory)
ProviderAdapterRegistry.register_factory("acp", _acp_factory)
