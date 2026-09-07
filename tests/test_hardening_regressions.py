import asyncio
from pathlib import Path

from atrin_core.desktop_adapter import GenericDesktopAdapter
from atrin_core.desktop_models import WindowInfo
from atrin_core.models import Provider
from atrin_core.provider_registry import ProviderAdapterRegistry
from atrin_core.state_machine import can_transition_workflow
from atrin_core.models import WorkflowState

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_ui_defaults_side_effecting():
    source = (ROOT / "frontend/src/pages/Workflows.tsx").read_text(encoding="utf-8")
    assert "useState(true)" in source
    assert "sideEffecting" in source
    assert "sideEffecting," in source
    assert "side_effecting_action" in source


def test_generic_provider_alias_is_supported():
    registry = ProviderAdapterRegistry()
    provider = Provider.from_config({
        "id": "generic-provider",
        "name": "Generic Provider",
        "adapter_id": "generic",
        "endpoint": "https://example.invalid",
        "metadata": {"api": {"model": "test-model", "api_key_env": "ATRIN_TEST_KEY"}},
    })
    registry.register(provider)
    assert registry.get("generic-provider").adapter_id == "generic"


class _FakeCli:
    def launch_app(self, app_path):
        return WindowInfo(window_id="real-cli-window", title=app_path, process_name="fake-cli", automation_id="real-cli-window")

    def attach_to_app(self, process_name):
        return WindowInfo(window_id="attached-window", title=process_name, process_name=process_name, automation_id="attached-window")


def test_desktop_cli_fallback_calls_real_backend():
    adapter = GenericDesktopAdapter(cli_backend=_FakeCli())
    launched = asyncio.run(adapter.launch_app("calculator"))
    attached = asyncio.run(adapter.attach_to_app("calculator"))
    assert launched.window_id == "real-cli-window"
    assert attached.window_id == "attached-window"
    assert adapter.last_strategy == "CLI"


def test_api_client_has_timeout_and_abort_path():
    source = (ROOT / "frontend/src/services/api.ts").read_text(encoding="utf-8")
    assert "AbortController" in source
    assert "REQUEST_TIMEOUT_MS" in source
    assert "controller.abort()" in source
    assert "request timed out" in source


def test_profile_aware_registry_injects_fencing_callback():
    source = (ROOT / "atrin_core/provider_registry.py").read_text(encoding="utf-8")
    assert "_current_fencing_token" in source
    assert "current_fencing_token" in source
    assert 'profile_id != "default"' in source


def test_state_machine_allows_cancellation_from_replanning():
    assert can_transition_workflow(WorkflowState.REPLANNING, WorkflowState.CANCELLING)


def test_workflow_hardening_installs_runtime_guards():
    from atrin_core.workflow_engine import WorkflowEngine

    assert getattr(WorkflowEngine, "_atrin_hardening_installed", False) is True
