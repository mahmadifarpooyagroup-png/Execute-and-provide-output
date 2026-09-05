import ast
import hashlib
import importlib.util
import inspect
from pathlib import Path

from .base import IPlugin


class PluginManager:
    """Load validated local plugins and manage their lifecycle."""

    _BLOCKED_IMPORTS = {
        "builtins",
        "ctypes",
        "importlib",
        "os",
        "pathlib",
        "shutil",
        "socket",
        "subprocess",
        "sys",
    }
    _BLOCKED_CALLS = {"__import__", "compile", "eval", "exec", "input", "open"}

    def __init__(self):
        self._plugins: dict[str, IPlugin] = {}
        self._metadata: dict[str, dict] = {}

    def register_plugin(self, plugin_path: str) -> str:
        path = Path(plugin_path).expanduser().resolve()
        if not path.is_file() or path.suffix != ".py":
            raise ValueError("Plugin path must point to a Python file")

        source = path.read_text(encoding="utf-8")
        self._validate_imports(source, path)
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
        plugin_id = metadata["plugin_id"]
        if plugin_id in self._plugins:
            raise ValueError(f"Plugin is already registered: {plugin_id}")
        if not plugin.initialize():
            raise RuntimeError(f"Plugin failed to initialize: {plugin_id}")

        self._plugins[plugin_id] = plugin
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
            imported_name = None
            if isinstance(node, ast.Import):
                imported_name = node.names[0].name
            elif isinstance(node, ast.ImportFrom):
                imported_name = node.module
            if imported_name and imported_name.split(".", 1)[0] in cls._BLOCKED_IMPORTS:
                raise ValueError(f"Plugin import is not allowed: {imported_name}")
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