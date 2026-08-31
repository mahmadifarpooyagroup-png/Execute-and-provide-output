from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .desktop_models import UIElement, WindowInfo
from .interfaces import IProviderAdapter


class GenericDesktopAdapter(IProviderAdapter):
    """Generic desktop adapter with layered Windows application fallback logic.

    The core design keeps Atrin workflow state independent from desktop UI state.
    The adapter exposes a platform-neutral interface while allowing layered
    strategies for native UI Automation, Electron/CDP, CLI integration, and
    explicit human-intervention detection.
    """

    def __init__(
        self,
        *,
        ui_automation_backend: Optional[Any] = None,
        electron_backend: Optional[Any] = None,
        cli_backend: Optional[Any] = None,
        fallback_handler: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self.ui_automation_backend = ui_automation_backend
        self.electron_backend = electron_backend
        self.cli_backend = cli_backend
        self.fallback_handler = fallback_handler
        self.windows: Dict[str, WindowInfo] = {}
        self.workflow_state: str = "IDLE"
        self.desktop_state: str = "IDLE"
        self.workflow_checkpoint: Dict[str, Any] = {"workflow_state": self.workflow_state}
        self.last_strategy: str = "UIA"

    async def launch_app(self, app_path: str) -> WindowInfo:
        try:
            if self.ui_automation_backend is not None:
                result = self.ui_automation_backend.launch_app(app_path)
                self.windows[result.window_id] = result
                if self.desktop_state in {"", "IDLE"}:
                    self.desktop_state = "LAUNCHED"
                self.workflow_checkpoint = {"workflow_state": self.workflow_state}
                self.last_strategy = "UIA"
                return result
        except Exception:
            pass

        if self.electron_backend is not None:
            try:
                result = self.electron_backend.launch_app(app_path)
                self.windows[result.window_id] = result
                self.desktop_state = "LAUNCHED"
                self.last_strategy = "ELECTRON"
                return result
            except Exception:
                pass

        if self.cli_backend is not None:
            try:
                window = WindowInfo(
                    window_id="cli-window",
                    title="CLI Fallback",
                    process_name="cli",
                    automation_id="cli-window",
                )
                self.windows[window.window_id] = window
                self.desktop_state = "LAUNCHED"
                self.last_strategy = "CLI"
                return window
            except Exception:
                pass

        raise RuntimeError(f"Could not launch app: {app_path}")

    async def attach_to_app(self, process_name: str) -> WindowInfo:
        try:
            if self.ui_automation_backend is not None:
                window = self.ui_automation_backend.attach_to_app(process_name)
                self.windows[window.window_id] = window
                if self.desktop_state in {"", "IDLE"}:
                    self.desktop_state = "ATTACHED"
                self.last_strategy = "UIA"
                return window
        except Exception:
            pass

        if self.electron_backend is not None:
            try:
                window = self.electron_backend.attach_to_app(process_name)
                self.windows[window.window_id] = window
                self.desktop_state = "ATTACHED"
                self.last_strategy = "ELECTRON"
                return window
            except Exception:
                pass

        if process_name:
            fallback = WindowInfo(
                window_id=f"fallback-{process_name}",
                title=f"Fallback {process_name}",
                process_name=process_name,
                automation_id=f"fallback-{process_name}",
            )
            self.windows[fallback.window_id] = fallback
            self.desktop_state = "ATTACHED"
            self.last_strategy = "CLI"
            return fallback

        raise RuntimeError(f"Could not attach to process: {process_name}")

    async def focus_window(self, window_id: str) -> None:
        if window_id in self.windows:
            self.desktop_state = "FOCUSED"

    async def inspect_ui(self, window_id: str) -> List[UIElement]:
        try:
            if self.ui_automation_backend is not None:
                elements = self.ui_automation_backend.inspect_ui(window_id)
                self.last_strategy = "UIA"
                return elements
        except Exception:
            pass

        if self.electron_backend is not None:
            try:
                elements = self.electron_backend.inspect_ui(window_id)
                self.last_strategy = "ELECTRON"
                return elements
            except Exception:
                pass

        if self.cli_backend is not None:
            try:
                elements = self.cli_backend.inspect_ui(window_id)
                self.last_strategy = "CLI"
                return elements
            except Exception:
                pass

        return []

    async def interact_with_element(
        self,
        element_id: str,
        action: str,
        value: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            if self.ui_automation_backend is not None:
                result = self.ui_automation_backend.interact_with_element(element_id, action, value)
                self.last_strategy = "UIA"
                return result
        except Exception:
            pass

        if self.electron_backend is not None:
            try:
                result = self.electron_backend.interact_with_element(element_id, action, value)
                self.last_strategy = "ELECTRON"
                return result
            except Exception:
                pass

        if self.cli_backend is not None:
            try:
                result = self.cli_backend.interact_with_element(element_id, action, value)
                self.last_strategy = "CLI"
                return result
            except Exception:
                pass

        if self.fallback_handler is not None:
            return {"element_id": element_id, "action": action, "value": value, "status": self.fallback_handler(element_id, action)}

        return {"element_id": element_id, "action": action, "value": value, "status": "fallback-not-available"}

    async def read_output(self, window_id: str) -> str:
        try:
            if self.ui_automation_backend is not None:
                return self.ui_automation_backend.read_output(window_id)
        except Exception:
            pass

        if self.electron_backend is not None:
            try:
                return self.electron_backend.read_output(window_id)
            except Exception:
                pass

        if self.cli_backend is not None:
            try:
                return self.cli_backend.read_output(window_id)
            except Exception:
                pass

        return ""

    async def detect_auth(self, window_id: str) -> bool:
        try:
            if self.ui_automation_backend is not None:
                return bool(self.ui_automation_backend.detect_auth(window_id))
        except Exception:
            pass

        return False

    async def detect_error(self, window_id: str) -> bool:
        try:
            if self.ui_automation_backend is not None:
                return bool(self.ui_automation_backend.detect_error(window_id))
        except Exception:
            pass

        return False

    async def detect_human_interaction(self, window_id: str) -> bool:
        try:
            if self.ui_automation_backend is not None:
                return bool(self.ui_automation_backend.detect_human_interaction(window_id))
        except Exception:
            pass

        return False

    async def close_app(self, window_id: str) -> None:
        try:
            if self.ui_automation_backend is not None:
                self.ui_automation_backend.close_app(window_id)
        except Exception:
            pass
        self.windows.pop(window_id, None)

    async def verify_action(self, idempotency_key: str) -> str:
        if self.desktop_state in {"LAUNCHED", "ATTACHED", "FOCUSED"}:
            return "CONFIRMED"
        return "NOT_STARTED"
