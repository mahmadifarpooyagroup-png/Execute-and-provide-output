from atrin_core.plugins.base import IPlugin
from atrin_core.plugins.manager import PluginManager


class MockPlugin(IPlugin):
    def get_metadata(self):
        return {"plugin_id": "mock", "name": "Mock Plugin", "version": "1.0.0"}

    def initialize(self):
        return True

    def execute(self, action, payload):
        return {"action": action, "payload": payload}

    def cleanup(self):
        pass


def _write_plugin(path, source):
    path.write_text(source, encoding="utf-8")


def test_plugin_registration_and_execution(tmp_path):
    plugin_path = tmp_path / "mock_plugin.py"
    _write_plugin(
        plugin_path,
        "from atrin_core.plugins.base import IPlugin\n\n"
        "class FilePlugin(IPlugin):\n"
        "    def get_metadata(self): return {'plugin_id': 'file-plugin', 'name': 'File Plugin', 'version': '1.0'}\n"
        "    def initialize(self): return True\n"
        "    def execute(self, action, payload): return {'action': action, 'payload': payload}\n"
        "    def cleanup(self): pass\n",
    )
    manager = PluginManager()

    assert manager.register_plugin(str(plugin_path)) == "file-plugin"
    assert manager.get_plugin("file-plugin").execute("ping", {"ok": True}) == {
        "action": "ping",
        "payload": {"ok": True},
    }
    assert manager.list_plugins()[0]["name"] == "File Plugin"


def test_plugin_without_contract_is_rejected(tmp_path):
    plugin_path = tmp_path / "invalid_plugin.py"
    _write_plugin(plugin_path, "class NotAPlugin: pass\n")

    manager = PluginManager()
    try:
        manager.register_plugin(str(plugin_path))
    except TypeError as error:
        assert "IPlugin" in str(error)
    else:
        raise AssertionError("Plugins without the IPlugin contract must be rejected")


def test_blocked_plugin_import_is_rejected(tmp_path):
    plugin_path = tmp_path / "unsafe_plugin.py"
    _write_plugin(plugin_path, "import subprocess\n")

    manager = PluginManager()
    try:
        manager.register_plugin(str(plugin_path))
    except ValueError as error:
        assert "not allowed" in str(error)
    else:
        raise AssertionError("Unsafe plugin imports must be rejected")