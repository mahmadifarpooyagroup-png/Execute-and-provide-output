from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workflows_page_loads_providers_on_direct_navigation():
    source = (ROOT / "frontend/src/pages/Workflows.tsx").read_text(encoding="utf-8")
    assert "loadProviders" in source
    assert "Promise.all([loadProviders(), loadWorkflows()])" in source


def test_api_profile_retry_reconciles_idempotent_conflict():
    source = (ROOT / "frontend/src/services/api.ts").read_text(encoding="utf-8")
    assert "class RuntimeApiError" in source
    assert "error.status === 409" in source
    assert "existing.profile_id === input.profile_id" in source
    assert "existing.provider_id === input.provider_id" in source


def test_frontend_storage_failures_do_not_break_runtime_ui():
    api_source = (ROOT / "frontend/src/services/api.ts").read_text(encoding="utf-8")
    store_source = (ROOT / "frontend/src/store/appStore.ts").read_text(encoding="utf-8")
    assert "sessionStorage" in api_source
    assert "Browser session storage is unavailable" in api_source
    assert "persistSettings" in store_source
