from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import multiprocessing as mp
import os
from pathlib import Path
from typing import Any

from .base import IPlugin


_SAFE_ENV_KEYS = {"PATH", "TEMP", "TMP", "USERPROFILE", "SYSTEMROOT", "COMSPEC", "PATHEXT", "HOME"}


def _plugin_worker(plugin_path: str, connection: Any) -> None:
    """Load and execute one plugin in a separate spawned process."""
    try:
        inherited_env = dict(os.environ)
        os.environ.clear()
        for key in _SAFE_ENV_KEYS:
            value = inherited_env.get(key)
            if value is not None:
                os.environ[key] = value
        path = Path(plugin_path).resolve()
        os.chdir(path.parent)
        module_name = f"atrin_plugin_{hashlib.sha256(str(path).encode()).hexdigest()}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Unable to load plugin from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin_types = [
            candidate
            for _, candidate in inspect.getmembers(module, inspect.isclass)
            if candidate is not IPlugin and issubclass(candidate, IPlugin)
        ]
        if len(plugin_types) != 1:
            raise TypeError("Plugin module must define exactly one IPlugin implementation")
        plugin = plugin_types[0]()
        metadata = plugin.get_metadata()
        if not isinstance(metadata, dict) or not all(
            isinstance(metadata.get(key), str) and metadata[key]
            for key in ("plugin_id", "name", "version")
        ):
            raise ValueError("Plugin metadata must contain non-empty plugin_id, name, and version")
        if not plugin.initialize():
            raise RuntimeError(f"Plugin failed to initialize: {metadata['plugin_id']}")
        connection.send({"ok": True, "metadata": dict(metadata)})

        while True:
            request = connection.recv()
            command = request.get("command") if isinstance(request, dict) else None
            if command == "execute":
                result = plugin.execute(request.get("action", ""), request.get("payload") or {})
                if not isinstance(result, dict):
                    raise TypeError("Plugin execute() must return a dict")
                connection.send({"ok": True, "result": result})
            elif command == "cleanup":
                plugin.cleanup()
                connection.send({"ok": True})
                return
            elif command == "metadata":
                connection.send({"ok": True, "metadata": dict(metadata)})
            else:
                raise ValueError("Unknown plugin worker command")
    except Exception as error:
        try:
            connection.send({"ok": False, "error": f"{type(error).__name__}: {error}"})
        except Exception:
            pass
    finally:
        try:
            connection.close()
        except Exception:
            pass


class _PluginProxy(IPlugin):
    """Synchronous IPC proxy for a plugin worker."""

    def __init__(self, plugin_path: Path, timeout: float = 30.0):
        self.plugin_path = plugin_path
        self.metadata: dict[str, str] = {}
        self.timeout = timeout
        context = mp.get_context("spawn")
        self._parent, child = context.Pipe()
        self._process = context.Process(target=_plugin_worker, args=(str(plugin_path), child), daemon=True)
        self._process.start()
        child.close()
        if not self._parent.poll(timeout):
            self._process.terminate()
            self._process.join(3)
            raise TimeoutError("Plugin worker initialization timed out")
        response = self._parent.recv()
        if not response.get("ok"):
            self._process.terminate()
            self._process.join(3)
            raise RuntimeError(response.get("error", "Plugin worker failed to initialize"))
        metadata = response.get("metadata")
        if not isinstance(metadata, dict):
            self.cleanup()
            raise RuntimeError("Plugin worker returned invalid metadata")
        self.metadata = {str(key): str(value) for key, value in metadata.items()}

    def get_metadata(self) -> dict:
        return dict(self.metadata)

    def initialize(self) -> bool:
        return True

    def execute(self, action: str, payload: dict) -> dict:
        if not self._process.is_alive():
            raise RuntimeError("Plugin worker is not running")
        self._parent.send({"command": "execute", "action": action, "payload": payload})
        if not self._parent.poll(self.timeout):
            self._process.terminate()
            self._process.join(3)
            raise TimeoutError(f"Plugin execution exceeded {self.timeout}s")
        response = self._parent.recv()
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "Plugin execution failed"))
        return response["result"]

    def cleanup(self) -> None:
        if not self._process.is_alive():
            try:
                self._parent.close()
            except Exception:
                pass
            return
        try:
            self._parent.send({"command": "cleanup"})
            if self._parent.poll(min(self.timeout, 5.0)):
                self._parent.recv()
        finally:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(3)
            self._parent.close()


class PluginManager:
    """Validate plugins and run them in isolated worker processes."""

    _BLOCKED_IMPORTS = {
        "builtins", "ctypes", "importlib", "os", "pathlib", "shutil", "socket", "subprocess", "sys",
    }
    _BLOCKED_CALLS = {"__import__", "compile", "eval", "exec", "input", "open"}

    def __init__(self, worker_timeout: float = 30.0):
        self._plugins: dict[str, _PluginProxy] = {}
        self._metadata: dict[str, dict] = {}
        self.worker_timeout = worker_timeout

    def register_plugin(self, plugin_path: str) -> str:
        path = Path(plugin_path).expanduser().resolve()
        if not path.is_file() or path.suffix != ".py":
            raise ValueError("Plugin path must point to a Python file")
        source = path.read_text(encoding="utf-8")
        self._validate_imports(source, path)

        proxy = _PluginProxy(path, self.worker_timeout)
        metadata = proxy.get_metadata()
        plugin_id = metadata["plugin_id"]
        if plugin_id in self._plugins:
            proxy.cleanup()
            raise ValueError(f"Plugin is already registered: {plugin_id}")
        self._plugins[plugin_id] = proxy
        self._metadata[plugin_id] = dict(metadata)
        return plugin_id

    def get_plugin(self, plugin_id: str) -> IPlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as error:
            raise KeyError(f"Plugin is not registered: {plugin_id}") from error

    def list_plugins(self) -> list[dict]:
        return [dict(self._metadata[plugin_id]) for plugin_id in self._plugins]

    @classmethod
    def _validate_imports(cls, source: str, path: Path) -> None:
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            raise ValueError(f"Plugin contains invalid Python: {error}") from error
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_name = alias.name
                    if imported_name.split(".", 1)[0] in cls._BLOCKED_IMPORTS:
                        raise ValueError(f"Plugin import is not allowed: {imported_name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module
                if module_name and module_name.split(".", 1)[0] in cls._BLOCKED_IMPORTS:
                    raise ValueError(f"Plugin import is not allowed: {module_name}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in cls._BLOCKED_CALLS:
                raise ValueError(f"Plugin call is not allowed: {node.func.id}")
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                raise ValueError("Plugin dunder attribute access is not allowed")

    def cleanup(self) -> None:
        cleanup_error: Exception | None = None
        for plugin in tuple(self._plugins.values()):
            try:
                plugin.cleanup()
            except Exception as error:
                cleanup_error = cleanup_error or error
        self._plugins.clear()
        self._metadata.clear()
        if cleanup_error is not None:
            raise RuntimeError("One or more plugins failed during cleanup") from cleanup_error
