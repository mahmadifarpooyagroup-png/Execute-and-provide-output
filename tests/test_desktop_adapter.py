from __future__ import annotations

from typing import List, Optional

import pytest

from atrin_core.desktop_adapter import GenericDesktopAdapter
from atrin_core.desktop_models import UIElement, WindowInfo


class DummyUIAutomationBackend:
    def __init__(self):
        self.windows = {
            "win-1": WindowInfo(
                window_id="win-1",
                title="TestApp - Ready",
                process_name="TestApp",
                automation_id="app-window",
            )
        }
        self.element_calls = []

    def launch_app(self, app_path: str) -> WindowInfo:
        return WindowInfo(
            window_id="win-1",
            title="TestApp - Ready",
            process_name="TestApp",
            automation_id="app-window",
        )

    def attach_to_app(self, process_name: str) -> WindowInfo:
        return self.windows["win-1"]

    def inspect_ui(self, window_id: str) -> List[UIElement]:
        return [
            UIElement(
                element_id="login-button",
                name="Login",
                control_type="Button",
                value=None,
                children=[],
            ),
            UIElement(
                element_id="status-text",
                name="Status",
                control_type="Text",
                value="ready",
                children=[],
            ),
        ]

    def interact_with_element(self, element_id: str, action: str, value: Optional[str] = None):
        self.element_calls.append((element_id, action, value))
        return {"element_id": element_id, "action": action, "value": value, "status": "ok"}

    def read_output(self, window_id: str) -> str:
        return "ready"

    def detect_auth(self, window_id: str) -> bool:
        return True

    def detect_error(self, window_id: str) -> bool:
        return False

    def detect_human_interaction(self, window_id: str) -> bool:
        return False

    def close_app(self, window_id: str) -> None:
        self.windows.pop(window_id, None)


class FailingUIAutomationBackend:
    def launch_app(self, app_path: str) -> WindowInfo:
        raise RuntimeError("UIA launch failed")

    def attach_to_app(self, process_name: str) -> WindowInfo:
        raise RuntimeError("UIA attach failed")

    def inspect_ui(self, window_id: str) -> List[UIElement]:
        raise RuntimeError("UIA unavailable")

    def interact_with_element(self, element_id: str, action: str, value: Optional[str] = None):
        raise RuntimeError("UIA unavailable")

    def read_output(self, window_id: str) -> str:
        raise RuntimeError("UIA unavailable")


class CliFallbackBackend:
    def inspect_ui(self, window_id: str) -> List[UIElement]:
        return [
            UIElement(
                element_id="cli-login",
                name="CLI Login",
                control_type="Button",
                value=None,
                children=[],
            )
        ]

    def interact_with_element(self, element_id: str, action: str, value: Optional[str] = None):
        return {"element_id": element_id, "action": action, "value": value, "status": "cli-ok"}

    def read_output(self, window_id: str) -> str:
        return "cli-ready"


@pytest.mark.asyncio
async def test_launch_app_and_attach_lifecycle():
    adapter = GenericDesktopAdapter(ui_automation_backend=DummyUIAutomationBackend())

    window = await adapter.launch_app("C:/Program Files/TestApp/TestApp.exe")
    assert window.process_name == "TestApp"
    assert window.window_id in adapter.windows

    attached = await adapter.attach_to_app("TestApp")
    assert attached.window_id == window.window_id

    assert await adapter.read_output(attached.window_id) == "ready"
    assert await adapter.detect_auth(attached.window_id) is True
    assert await adapter.detect_error(attached.window_id) is False

    await adapter.close_app(attached.window_id)
    assert attached.window_id not in adapter.windows


@pytest.mark.asyncio
async def test_ui_inspection_and_element_interaction():
    backend = DummyUIAutomationBackend()
    adapter = GenericDesktopAdapter(ui_automation_backend=backend)

    window = await adapter.launch_app("C:/Program Files/TestApp/TestApp.exe")
    elements = await adapter.inspect_ui(window.window_id)
    assert len(elements) == 2
    assert elements[0].name == "Login"

    response = await adapter.interact_with_element("login-button", "click", None)
    assert response["status"] == "ok"
    assert backend.element_calls == [("login-button", "click", None)]


@pytest.mark.asyncio
async def test_fallback_to_cli_when_uia_fails():
    adapter = GenericDesktopAdapter(
        ui_automation_backend=FailingUIAutomationBackend(),
        cli_backend=CliFallbackBackend(),
    )

    window = await adapter.launch_app("C:/Program Files/TestApp/TestApp.exe")
    elements = await adapter.inspect_ui(window.window_id)
    assert elements[0].element_id == "cli-login"
    assert adapter.last_strategy == "CLI"

    response = await adapter.interact_with_element("cli-login", "click", "submit")
    assert response["status"] == "cli-ok"
    assert await adapter.read_output(window.window_id) == "cli-ready"


@pytest.mark.asyncio
async def test_protocol_state_is_independent_from_workflow_state_and_checkpoints():
    adapter = GenericDesktopAdapter(ui_automation_backend=DummyUIAutomationBackend())
    adapter.workflow_state = "WAITING_FOR_USER"
    adapter.desktop_state = "FOCUSED"

    await adapter.launch_app("C:/Program Files/TestApp/TestApp.exe")

    assert adapter.workflow_state == "WAITING_FOR_USER"
    assert adapter.desktop_state == "FOCUSED"
    assert adapter.windows
    assert adapter.workflow_checkpoint == {"workflow_state": "WAITING_FOR_USER"}
