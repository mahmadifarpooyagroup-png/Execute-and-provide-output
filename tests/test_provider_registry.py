import asyncio
import json

import pytest

from atrin_core.database import AtrinDatabase
from atrin_core.models import Provider
from atrin_core.provider_registry import CompatibleChatAdapter, ProviderAdapterRegistry


def test_registry_catalog_and_chat_adapter_config():
    registry = ProviderAdapterRegistry()
    provider = registry.register({
        "id": "local-api",
        "name": "Local API",
        "adapter_id": "chat-completions",
        "endpoint": "http://127.0.0.1:9000/v1",
        "metadata": {
            "api": {
                "model": "demo-model",
                "api_key_env": "DEMO_API_KEY",
            },
            "capabilities": ["chat", "streaming"],
        },
    })
    assert isinstance(provider, Provider)
    catalog = registry.catalog()
    assert catalog[0]["id"] == "local-api"
    assert "chat" in catalog[0]["capabilities"]
    assert "api" in catalog[0]["capabilities"]


def test_registry_accepts_legacy_compatible_chat_alias():
    registry = ProviderAdapterRegistry()
    provider = registry.register({
        "id": "legacy-api",
        "adapter_id": "openai-compatible",
        "endpoint": "http://127.0.0.1:9000/v1",
        "metadata": {"api": {"model": "demo-model", "api_key_env": "DEMO_API_KEY"}},
    })
    assert provider.adapter_id == "openai-compatible"
    assert registry.catalog()[0]["capabilities"] == ["api", "chat", "text"]


def test_registry_rejects_unknown_adapter():
    registry = ProviderAdapterRegistry()
    with pytest.raises(ValueError, match="Unsupported provider adapter"):
        registry.register({"id": "broken", "adapter_id": "not-installed"})


def test_registry_can_load_json_file(tmp_path, monkeypatch):
    config = tmp_path / "providers.json"
    config.write_text(json.dumps([
        {"id": "web-demo", "adapter_id": "generic-web", "endpoint": "data:text/html,<body></body>"}
    ]), encoding="utf-8")
    monkeypatch.setenv("ATRIN_PROVIDERS_FILE", str(config))
    registry = ProviderAdapterRegistry.from_environment()
    assert registry.get("web-demo").adapter_id == "generic-web"


def test_profile_aware_adapter_resolves_profile_from_durable_step(tmp_path):
    database = AtrinDatabase(str(tmp_path / "atrin.db"))
    registry = ProviderAdapterRegistry()
    created: list[tuple[str, str]] = []

    def fake_factory(current_provider, profile_id):
        created.append((current_provider.id, profile_id or ""))
        return _FakeAdapter()

    ProviderAdapterRegistry.register_factory("test-profile-aware", fake_factory)
    provider = registry.register({"id": "p-test", "adapter_id": "test-profile-aware"})
    connection = database.get_connection()
    try:
        connection.execute("INSERT INTO workflows(workflow_id,goal,state) VALUES ('w1','goal','IDLE')")
        connection.execute("INSERT INTO tasks(task_id,workflow_id,description,status,order_index) VALUES ('t1','w1','task','PENDING',0)")
        connection.execute(
            "INSERT INTO steps(step_id,task_id,action,provider_id,idempotency_key,operation_id,status,order_index,provider_profile_id) "
            "VALUES ('s1','t1','do','p-test','k1','op1','PENDING',0,'profile-42')"
        )
        connection.commit()
    finally:
        connection.close()

    adapters = registry.build_adapters(database)
    result = asyncio.run(adapters[provider.id].execute("do", "k1", operation_id="op1"))
    assert result["result"] == "ok"
    assert created == [("p-test", "profile-42")]


class _FakeAdapter:
    async def execute(self, action, idempotency_key, *, operation_id=None, fencing_token=None):
        return {"result": "ok"}

    async def verify_action(self, idempotency_key, *, operation_id=None):
        return "CONFIRMED"

    async def cancel(self, idempotency_key, *, operation_id=None):
        return False


def test_chat_response_extraction():
    assert CompatibleChatAdapter._extract_text({"choices": [{"message": {"content": "hello"}}]}) == "hello"
    assert CompatibleChatAdapter._extract_text({"choices": [{"text": "hello"}]}) == "hello"
    assert CompatibleChatAdapter._extract_text({"output_text": "hello"}) == "hello"


def test_registry_normalizes_string_capabilities():
    registry = ProviderAdapterRegistry()
    provider = registry.register({
        "id": "string-capability",
        "adapter_id": "api",
        "metadata": {"capabilities": "chat"},
    })
    assert provider.id == "string-capability"
    assert registry.catalog()[0]["capabilities"] == ["api", "chat", "text"]
