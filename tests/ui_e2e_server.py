from __future__ import annotations

import os

import uvicorn

from atrin_core.interfaces import IProviderAdapter
from atrin_core.provider_registry import ProviderAdapterRegistry
from atrin_core.runtime import create_app
from atrin_core.security import LocalSecurityManager


class E2EFakeAdapter(IProviderAdapter):
    async def execute(self, action, idempotency_key, *, operation_id=None, fencing_token=None):
        return {
            "result": f"Executed: {action}",
            "evidence": "e2e-evidence",
            "operation_id": operation_id,
        }

    async def verify_action(self, idempotency_key, *, operation_id=None):
        return "CONFIRMED"

    async def cancel(self, idempotency_key, *, operation_id=None):
        return True


def build_app():
    db_path = os.environ.get("ATRIN_DB_PATH", ".atrin_data/ui-e2e.db")
    token_path = os.environ.get("ATRIN_RUNTIME_TOKEN_PATH", ".atrin_data/ui-e2e.token")
    expected_token = os.environ.get("ATRIN_E2E_TOKEN")
    if expected_token:
        os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as stream:
            stream.write(expected_token)
        if os.name != "nt":
            os.chmod(token_path, 0o600)

    registry = ProviderAdapterRegistry()
    registry.register_factory("e2e-fake", lambda provider, profile_id: E2EFakeAdapter())
    registry.register({
        "id": "e2e-provider",
        "name": "E2E Provider",
        "adapter_id": "e2e-fake",
        "connection_kind": "API",
        "metadata": {"capabilities": ["chat", "test"]},
    })
    return create_app(db_path=db_path, token_path=token_path, provider_registry=registry)


if __name__ == "__main__":
    port = int(os.environ.get("ATRIN_UI_E2E_PORT", "8765"))
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
