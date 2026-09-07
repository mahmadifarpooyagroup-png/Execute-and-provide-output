from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .desktop_models import UIElement, WindowInfo
from .interfaces import IProviderAdapter


class GenericDesktopAdapter(IProviderAdapter):
    """Generic desktop adapter with explicit action execution and verification."""

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
        self._last_action_key: Optional[str] = None
        self._last_action_result: Optional[Dict[str, Any]] = None
        self.fallback_errors: List[Dict[str, str]] = []

    def _record_fallback_error(self, strategy: str, error: Exception) -> None:
        self.fallback_errors.append({
            "strategy": strategy,
            "exception_type": type(error).__name__,
            "message": str(error),
        })

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
        except Exception as error:
            self._record_fallback_error("UIA.launch", error)

        if self.electron_backend is not None:
            try:
                result = self.electron_backend.launch_app(app_path)
                self.windows[result.window_id] = result
                self.desktop_state = "LAUNCHED"
                self.last_strategy = "ELECTRON"
                return result
            except Exception as error:
                self._record_fallback_error("ELECTRON.launch", error)

        if self.cli_backend is not None:
            try:
                window = WindowInfo(window_id="cli-window", title="CLI Fallback",
                                    process_name="cli", automation_id="cli-window")
                self.windows[window.window_id] = window
                self.desktop_state = "LAUNCHED"
                self.last_strategy = "CLI"
                return window
            except Exception as error:
                self._record_fallback_error("CLI.launch", error)

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
        except Exception as error:
            self._record_fallback_error("UIA.attach", error)

        if self.electron_backend is not None:
            try:
                window = self.electron_backend.attach_to_app(process_name)
                self.windows[window.window_id] = window
                self.desktop_state = "ATTACHED"
                self.last_strategy = "ELECTRON"
                return window
            except Exception as error:
                self._record_fallback_error("ELECTRON.attach", error)

        if process_name:
            fallback = WindowInfo(window_id=f"fallback-{process_name}", title=f"Fallback {process_name}",
                                  process_name=process_name, automation_id=f"fallback-{process_name}")
            self.windows[fallback.window_id] = fallback
            self.desktop_state = "ATTACHED"
            self.last_strategy = "CLI"
            return fallback

        raise RuntimeError(f"Could not attach to process: {process_name}")

    async def focus_window(self, window_id: str) -> None:
        if window_id not in self.windows:
            raise LookupError(f"Window not found: {window_id}")
        self.desktop_state = "FOCUSED"

    async def inspect_ui(self, window_id: str) -> List[UIElement]:
        try:
            if self.ui_automation_backend is not None:
                elements = self.ui_automation_backend.inspect_ui(window_id)
                self.last_strategy = "UIA"
                return elements
        except Exception as error:
            self._record_fallback_error("UIA.inspect", error)

        if self.electron_backend is not None:
            try:
                elements = self.electron_backend.inspect_ui(window_id)
                self.last_strategy = "ELECTRON"
                return elements
            except Exception as error:
                self._record_fallback_error("ELECTRON.inspect", error)

        if self.cli_backend is not None:
            try:
                elements = self.cli_backend.inspect_ui(window_id)
                self.last_strategy = "CLI"
                return elements
            except Exception as error:
                self._record_fallback_error("CLI.inspect", error)

        return []

    async def interact_with_element(self, element_id: str, action: str,
                                    value: Optional[str] = None) -> Dict[str, Any]:
        for name, backend in (("UIA", self.ui_automation_backend),
                              ("ELECTRON", self.electron_backend),
                              ("CLI", self.cli_backend)):
            if backend is None:
                continue
            try:
                result = backend.interact_with_element(element_id, action, value)
                self.last_strategy = name
                return result
            except Exception as error:
                self._record_fallback_error(f"{name}.interact", error)

        if self.fallback_handler is not None:
            return {"element_id": element_id, "action": action, "value": value,
                    "status": self.fallback_handler(element_id, action)}
        return {"element_id": element_id, "action": action, "value": value,
                "status": "fallback-not-available"}

    async def execute(self, action: str, idempotency_key: str, *, fencing_token: Optional[int] = None) -> Dict[str, Any]:
        self._last_action_key = idempotency_key
        if fencing_token is not None:
            # Desktop backends that support fencing may expose a matching hook.
            for backend in (self.ui_automation_backend, self.electron_backend, self.cli_backend):
                current = getattr(backend, "current_fencing_token", None) if backend is not None else None
                if callable(current) and int(fencing_token) != int(current()):
                    raise PermissionError("Invalid fencing token for desktop execution")

        for name, backend in (("UIA", self.ui_automation_backend),
                              ("ELECTRON", self.electron_backend),
                              ("CLI", self.cli_backend)):
            method = getattr(backend, "execute", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                result = method(action, idempotency_key)
                self.last_strategy = name
                normalized = result if isinstance(result, dict) else {"result": result}
                self._last_action_result = normalized
                return normalized
            except Exception as error:
                self._record_fallback_error(f"{name}.execute", error)

        raise RuntimeError("No desktop backend exposes a verified execute(action, idempotency_key) operation")

    async def read_output(self, window_id: str) -> str:
        for name, backend in (("UIA", self.ui_automation_backend),
                              ("ELECTRON", self.electron_backend),
                              ("CLI", self.cli_backend)):
            method = getattr(backend, "read_output", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                self.last_strategy = name
                return method(window_id)
            except Exception as error:
                self._record_fallback_error(f"{name}.read_output", error)
        return ""

    async def detect_auth(self, window_id: str) -> bool:
        method = getattr(self.ui_automation_backend, "detect_auth", None)
        if callable(method):
            try:
                return bool(method(window_id))
            except Exception as error:
                self._record_fallback_error("UIA.detect_auth", error)
        return False

    async def detect_error(self, window_id: str) -> bool:
        method = getattr(self.ui_automation_backend, "detect_error", None)
        if callable(method):
            try:
                return bool(method(window_id))
            except Exception as error:
                self._record_fallback_error("UIA.detect_error", error)
        return False

    async def detect_human_interaction(self, window_id: str) -> bool:
        method = getattr(self.ui_automation_backend, "detect_human_interaction", None)
        if callable(method):
            try:
                return bool(method(window_id))
            except Exception as error:
                self._record_fallback_error("UIA.detect_human_interaction", error)
        return False

    async def close_app(self, window_id: str) -> None:
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend)):
            method = getattr(backend, "close_app", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                method(window_id)
                break
            except Exception as error:
                self._record_fallback_error(f"{name}.close", error)
        self.windows.pop(window_id, None)

    async def verify_action(self, idempotency_key: str) -> str:
        if self._last_action_key != idempotency_key:
            return "AMBIGUOUS"
        for backend in (self.ui_automation_backend, self.electron_backend, self.cli_backend):
            verifier = getattr(backend, "verify_action", None) if backend is not None else None
            if callable(verifier):
                try:
                    status = str(verifier(idempotency_key)).upper()
                    return status if status in {"CONFIRMED", "NOT_STARTED", "FAILED", "AMBIGUOUS"} else "AMBIGUOUS"
                except Exception as error:
                    self._record_fallback_error("verify_action", error)
        # Being merely launched/attached/focused is not proof that a side effect happened.
        return "AMBIGUOUS"
