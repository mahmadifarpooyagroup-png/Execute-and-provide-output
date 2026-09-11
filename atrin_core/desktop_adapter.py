from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional

from .desktop_models import UIElement, WindowInfo
from .interfaces import IProviderAdapter


class GenericDesktopAdapter(IProviderAdapter):
    """Generic desktop adapter with explicit execution, verification and fallback telemetry."""

    def __init__(
        self,
        *,
        ui_automation_backend: Optional[Any] = None,
        electron_backend: Optional[Any] = None,
        cli_backend: Optional[Any] = None,
        fallback_handler: Optional[Callable[[str, str], str]] = None,
        current_fencing_token: Optional[Callable[[], int]] = None,
    ) -> None:
        self.ui_automation_backend = ui_automation_backend
        self.electron_backend = electron_backend
        self.cli_backend = cli_backend
        self.fallback_handler = fallback_handler
        self.current_fencing_token = current_fencing_token
        self.windows: Dict[str, WindowInfo] = {}
        self.workflow_state: str = "IDLE"
        self.desktop_state: str = "IDLE"
        self.workflow_checkpoint: Dict[str, Any] = {"workflow_state": self.workflow_state}
        self.last_strategy: str = "UIA"
        self._last_action_key: Optional[str] = None
        self._last_operation_id: Optional[str] = None
        self._last_action_result: Optional[Dict[str, Any]] = None
        self.fallback_errors: List[Dict[str, str]] = []

    def _record_fallback_error(self, strategy: str, error: Exception) -> None:
        self.fallback_errors.append({
            "strategy": strategy,
            "exception_type": type(error).__name__,
            "message": str(error),
        })

    async def _call_backend(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        result = method(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    async def launch_app(self, app_path: str) -> WindowInfo:
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
            method = getattr(backend, "launch_app", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                result = await self._call_backend(method, app_path)
                if not isinstance(result, WindowInfo):
                    raise TypeError(f"{name}.launch_app must return WindowInfo")
                self.windows[result.window_id] = result
                self.desktop_state = "LAUNCHED"
                self.workflow_checkpoint = {"workflow_state": self.workflow_state}
                self.last_strategy = name
                return result
            except Exception as error:
                self._record_fallback_error(f"{name}.launch", error)
        raise RuntimeError(f"Could not launch app: {app_path}")

    async def attach_to_app(self, process_name: str) -> WindowInfo:
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
            method = getattr(backend, "attach_to_app", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                window = await self._call_backend(method, process_name)
                if not isinstance(window, WindowInfo):
                    raise TypeError(f"{name}.attach_to_app must return WindowInfo")
                self.windows[window.window_id] = window
                self.desktop_state = "ATTACHED"
                self.last_strategy = name
                return window
            except Exception as error:
                self._record_fallback_error(f"{name}.attach", error)
        raise RuntimeError(f"Could not attach to process: {process_name}")

    async def focus_window(self, window_id: str) -> None:
        if window_id not in self.windows:
            raise LookupError(f"Window not found: {window_id}")
        self.desktop_state = "FOCUSED"

    async def inspect_ui(self, window_id: str) -> List[UIElement]:
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
            if backend is None:
                continue
            try:
                elements = backend.inspect_ui(window_id)
                self.last_strategy = name
                return elements
            except Exception as error:
                self._record_fallback_error(f"{name}.inspect", error)
        return []

    async def interact_with_element(self, element_id: str, action: str, value: Optional[str] = None) -> Dict[str, Any]:
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
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
        # FIX (بند ۷): was silently returning fallback-not-available which could be
        # mistaken for success. Raise so the engine records AMBIGUOUS/FAILED properly.
        raise RuntimeError(
            f"Desktop interaction failed: no backend could execute action={action!r} "
            f"on element={element_id!r}. "
            f"Errors: {self.fallback_errors[-3:]}"
        )

    @staticmethod
    def _supports_keyword(method: Any, name: str) -> bool:
        try:
            parameters = inspect.signature(method).parameters.values()
        except (TypeError, ValueError):
            return True
        return any(p.kind == inspect.Parameter.VAR_KEYWORD or p.name == name for p in parameters)

    async def execute(self, action: str, idempotency_key: str, *, operation_id: str | None = None,
                      fencing_token: Optional[int] = None) -> Dict[str, Any]:
        if self.current_fencing_token is not None:
            if fencing_token is None or int(fencing_token) != int(self.current_fencing_token()):
                raise PermissionError("Invalid or missing fencing token for desktop execution")
        self._last_action_key = idempotency_key
        self._last_operation_id = operation_id
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
            method = getattr(backend, "execute", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                kwargs: dict[str, Any] = {}
                if self._supports_keyword(method, "operation_id"):
                    kwargs["operation_id"] = operation_id
                if self._supports_keyword(method, "fencing_token"):
                    kwargs["fencing_token"] = fencing_token
                result = method(action, idempotency_key, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                self.last_strategy = name
                normalized = result if isinstance(result, dict) else {"result": result}
                self._last_action_result = normalized
                return normalized
            except Exception as error:
                self._record_fallback_error(f"{name}.execute", error)
        raise RuntimeError("No desktop backend exposes a verified execute operation")

    async def read_output(self, window_id: str) -> str:
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
            method = getattr(backend, "read_output", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                value = method(window_id)
                if inspect.isawaitable(value):
                    value = await value
                self.last_strategy = name
                return str(value)
            except Exception as error:
                self._record_fallback_error(f"{name}.read_output", error)
        return ""

    async def detect_auth(self, window_id: str) -> bool:
        method = getattr(self.ui_automation_backend, "detect_auth", None)
        if callable(method):
            try:
                result = method(window_id)
                return bool(await result if inspect.isawaitable(result) else result)
            except Exception as error:
                self._record_fallback_error("UIA.detect_auth", error)
        return False

    async def detect_error(self, window_id: str) -> bool:
        method = getattr(self.ui_automation_backend, "detect_error", None)
        if callable(method):
            try:
                result = method(window_id)
                return bool(await result if inspect.isawaitable(result) else result)
            except Exception as error:
                self._record_fallback_error("UIA.detect_error", error)
        return False

    async def detect_human_interaction(self, window_id: str) -> bool:
        method = getattr(self.ui_automation_backend, "detect_human_interaction", None)
        if callable(method):
            try:
                result = method(window_id)
                return bool(await result if inspect.isawaitable(result) else result)
            except Exception as error:
                self._record_fallback_error("UIA.detect_human_interaction", error)
        return False

    async def close_app(self, window_id: str) -> None:
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend)):
            method = getattr(backend, "close_app", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                result = method(window_id)
                if inspect.isawaitable(result):
                    await result
                break
            except Exception as error:
                self._record_fallback_error(f"{name}.close", error)
        self.windows.pop(window_id, None)

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> str:
        if self._last_action_key != idempotency_key or self._last_operation_id != operation_id:
            return "AMBIGUOUS"
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
            verifier = getattr(backend, "verify_action", None) if backend is not None else None
            if not callable(verifier):
                continue
            try:
                result = verifier(idempotency_key, operation_id=operation_id) if self._supports_keyword(verifier, "operation_id") else verifier(idempotency_key)
                result = await result if inspect.isawaitable(result) else result
                status = str(result).upper()
                return status if status in {"CONFIRMED", "NOT_STARTED", "FAILED", "AMBIGUOUS"} else "AMBIGUOUS"
            except Exception as error:
                self._record_fallback_error(f"{name}.verify", error)
        return "AMBIGUOUS"

    async def cancel(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        if self._last_action_key != idempotency_key or self._last_operation_id != operation_id:
            return False
        for name, backend in (("UIA", self.ui_automation_backend), ("ELECTRON", self.electron_backend), ("CLI", self.cli_backend)):
            method = getattr(backend, "cancel", None) if backend is not None else None
            if not callable(method):
                continue
            try:
                result = method(idempotency_key, operation_id=operation_id) if self._supports_keyword(method, "operation_id") else method(idempotency_key)
                result = await result if inspect.isawaitable(result) else result
                self.last_strategy = name
                return bool(result)
            except Exception as error:
                self._record_fallback_error(f"{name}.cancel", error)
        return False
