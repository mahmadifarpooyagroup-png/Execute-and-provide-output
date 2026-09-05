import ast
from pathlib import Path


def _read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_major_ui_routes_and_wizard_are_declared():
    app_source = _read_file("frontend/src/App.tsx")
    for route in ["/dashboard", "/providers", "/workflows", "/recovery", "/settings", "/first-run"]:
        assert route in app_source, f"Missing route declaration for {route}"

    wizard_source = _read_file("frontend/src/pages/FirstRunWizard.tsx")
    assert "first_run_wizard" in wizard_source
    assert "continue_setup" in wizard_source


def test_provider_and_workflow_pages_render_mock_data():
    providers_source = _read_file("frontend/src/pages/Providers.tsx")
    workflows_source = _read_file("frontend/src/pages/Workflows.tsx")
    mock_api_source = _read_file("frontend/src/services/mockApi.ts")

    assert "providers.map" in providers_source
    assert "workflows.map" in workflows_source
    assert "getProviders" in mock_api_source
    assert "getWorkflows" in mock_api_source
    assert "connected_providers" in providers_source
    assert "workflow_engine" in workflows_source


def test_dashboard_and_layout_components_are_present():
    dashboard_source = _read_file("frontend/src/pages/Dashboard.tsx")
    layout_source = _read_file("frontend/src/components/Layout.tsx")

    assert "total_providers" in dashboard_source
    assert "providers" in layout_source
    assert "recovery" in layout_source
    assert "Settings" in layout_source
