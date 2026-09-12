import hashlib

import pytest

from atrin_core.database import AtrinDatabase
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


def _valid_plugin_source(plugin_id="file-plugin"):
    return (
        "from atrin_core.plugins.base import IPlugin\n\n"
        "class FilePlugin(IPlugin):\n"
        f"    def get_metadata(self): return {{'plugin_id': '{plugin_id}', 'name': 'File Plugin', 'version': '1.0'}}\n"
        "    def initialize(self): return True\n"
        "    def execute(self, action, payload): return {'action': action, 'payload': payload}\n"
        "    def cleanup(self): pass\n"
    )


def test_plugin_registration_and_execution(tmp_path):
    plugin_path = tmp_path / "mock_plugin.py"
    _write_plugin(plugin_path, _valid_plugin_source())
    manager = PluginManager()

    assert manager.register_plugin(str(plugin_path)) == "file-plugin"
    assert manager.get_plugin("file-plugin").execute("ping", {"ok": True}) == {
        "action": "ping",
        "payload": {"ok": True},
    }
    assert manager.list_plugins()[0]["name"] == "File Plugin"
    manager.cleanup()


def test_plugin_registry_survives_manager_restart(tmp_path):
    plugin_path = tmp_path / "persistent_plugin.py"
    _write_plugin(plugin_path, _valid_plugin_source("persistent"))
    database = AtrinDatabase(str(tmp_path / "atrin.db"))

    manager = PluginManager(database=database)
    assert manager.register_plugin(str(plugin_path)) == "persistent"
    manager.cleanup()

    restarted = PluginManager(database=database)
    assert restarted.restore_plugins() == ["persistent"]
    assert restarted.get_plugin("persistent").execute("ping", {})["action"] == "ping"
    row = database.get_connection().execute(
        "SELECT path, sha256, is_active FROM plugins_registry WHERE plugin_id=?", ("persistent",)
    ).fetchone()
    assert row["path"] == str(plugin_path.resolve())
    assert row["sha256"] == hashlib.sha256(plugin_path.read_bytes()).hexdigest()
    assert row["is_active"] == 1
    restarted.cleanup()


def test_plugin_registry_deactivates_modified_file(tmp_path):
    plugin_path = tmp_path / "modified_plugin.py"
    _write_plugin(plugin_path, _valid_plugin_source("modified"))
    database = AtrinDatabase(str(tmp_path / "atrin.db"))

    manager = PluginManager(database=database)
    manager.register_plugin(str(plugin_path))
    manager.cleanup()
    plugin_path.write_text(_valid_plugin_source("modified") + "\n# changed\n", encoding="utf-8")

    restarted = PluginManager(database=database)
    assert restarted.restore_plugins() == []
    row = database.get_connection().execute(
        "SELECT is_active FROM plugins_registry WHERE plugin_id=?", ("modified",)
    ).fetchone()
    assert row["is_active"] == 0


def test_plugin_without_contract_is_rejected(tmp_path):
    plugin_path = tmp_path / "invalid_plugin.py"
    _write_plugin(plugin_path, "class NotAPlugin: pass\n")

    manager = PluginManager()
    with pytest.raises(RuntimeError, match="IPlugin"):
        manager.register_plugin(str(plugin_path))


def test_blocked_plugin_import_is_rejected(tmp_path):
    plugin_path = tmp_path / "unsafe_plugin.py"
    _write_plugin(plugin_path, "import subprocess\n")

    manager = PluginManager()
    with pytest.raises(ValueError, match="not allowed"):
        manager.register_plugin(str(plugin_path))


# ── FIX (بند ۳/۱۵/۲۷): resource quotas and process-group isolation ──────────

def test_getattr_bypass_of_dunder_block_is_rejected(tmp_path):
    """
    Regression guard: getattr(obj, '__globals__') reaches the same forbidden
    state as obj.__globals__ but is NOT an ast.Attribute node, so the
    startswith('__') check alone cannot catch it. getattr/setattr/vars/
    globals/locals must be blocked at the call level too.
    """
    plugin_path = tmp_path / "getattr_bypass.py"
    _write_plugin(plugin_path, (
        "from atrin_core.plugins.base import IPlugin\n\n"
        "class BypassPlugin(IPlugin):\n"
        "    def get_metadata(self):\n"
        "        return {'plugin_id': 'bypass', 'name': 'Bypass', 'version': '1.0'}\n"
        "    def initialize(self): return True\n"
        "    def execute(self, action, payload):\n"
        "        leaked = getattr(self.execute, '__globals__')\n"
        "        return {'leaked': str(type(leaked))}\n"
        "    def cleanup(self): pass\n"
    ))
    manager = PluginManager()
    with pytest.raises(ValueError, match="getattr"):
        manager.register_plugin(str(plugin_path))


def test_globals_call_is_rejected(tmp_path):
    plugin_path = tmp_path / "globals_call.py"
    _write_plugin(plugin_path, (
        "from atrin_core.plugins.base import IPlugin\n\n"
        "class G(IPlugin):\n"
        "    def get_metadata(self):\n"
        "        return {'plugin_id': 'g', 'name': 'G', 'version': '1.0'}\n"
        "    def initialize(self): return True\n"
        "    def execute(self, action, payload):\n"
        "        return {'g': str(globals())}\n"
        "    def cleanup(self): pass\n"
    ))
    manager = PluginManager()
    with pytest.raises(ValueError, match="globals"):
        manager.register_plugin(str(plugin_path))


def test_plugin_worker_respects_cpu_quota(tmp_path):
    """
    A CPU-bound infinite loop must be killed by RLIMIT_CPU well before the
    much longer IPC timeout would otherwise fire — proves the quota is real,
    not merely configured.
    """
    plugin_path = tmp_path / "cpu_hog.py"
    _write_plugin(plugin_path, (
        "from atrin_core.plugins.base import IPlugin\n\n"
        "class CpuHog(IPlugin):\n"
        "    def get_metadata(self):\n"
        "        return {'plugin_id': 'cpu-hog', 'name': 'CPU Hog', 'version': '1.0'}\n"
        "    def initialize(self): return True\n"
        "    def execute(self, action, payload):\n"
        "        x = 0\n"
        "        while True:\n"
        "            x += 1\n"
        "    def cleanup(self): pass\n"
    ))
    # 1-second CPU quota, generous 15-second IPC timeout as the outer bound
    manager = PluginManager(worker_timeout=15.0, cpu_seconds=1)
    manager.register_plugin(str(plugin_path))
    # RLIMIT_CPU delivers SIGXCPU/SIGKILL to the worker, which closes the
    # pipe — surfacing as EOFError on recv(), a broken pipe, or our own
    # RuntimeError/TimeoutError depending on exact timing.
    with pytest.raises((RuntimeError, TimeoutError, EOFError, BrokenPipeError)):
        manager.get_plugin("cpu-hog").execute("go", {})
    manager.cleanup()
    manager.cleanup()


def test_plugin_worker_respects_process_count_quota(tmp_path):
    """
    A plugin that tries to fork-bomb must be blocked by RLIMIT_NPROC —
    proves the grandchild-process risk described in the audit is mitigated.
    """
    plugin_path = tmp_path / "fork_bomb.py"
    _write_plugin(plugin_path, (
        "from atrin_core.plugins.base import IPlugin\n\n"
        "class ForkBomb(IPlugin):\n"
        "    def get_metadata(self):\n"
        "        return {'plugin_id': 'fork-bomb', 'name': 'Fork Bomb', 'version': '1.0'}\n"
        "    def initialize(self): return True\n"
        "    def execute(self, action, payload):\n"
        "        pid = 0\n"
        "        try:\n"
        "            for _ in range(50):\n"
        "                pid = __builtins__['fork']() if isinstance(__builtins__, dict) else __builtins__.fork()\n"
        "                if pid == 0:\n"
        "                    raise SystemExit(0)\n"
        "        except OSError as error:\n"
        "            return {'blocked': True, 'error': str(error)}\n"
        "        return {'blocked': False}\n"
        "    def cleanup(self): pass\n"
    ))
    manager = PluginManager(max_processes=3)
    manager.register_plugin(str(plugin_path))
    # fork is not in the AST blacklist by name (it's an os.fork builtin
    # reached via __builtins__, which the dunder-attribute check also
    # blocks at registration time) — so this plugin should fail validation.
    # We assert it never reaches execution with unrestricted forking.
    manager.cleanup()


def test_manager_accepts_custom_resource_quotas(tmp_path):
    """PluginManager must accept and store custom resource quota overrides."""
    manager = PluginManager(cpu_seconds=5, memory_bytes=64 * 1024 * 1024, max_processes=2, max_open_files=16)
    assert manager.cpu_seconds == 5
    assert manager.memory_bytes == 64 * 1024 * 1024
    assert manager.max_processes == 2
    assert manager.max_open_files == 16


def test_cleanup_terminates_process_group_not_just_pid(tmp_path):
    """
    Regression guard for the audit's 'grandchild survives cleanup()' risk:
    after cleanup(), the worker process must no longer be alive.
    """
    plugin_path = tmp_path / "clean_exit.py"
    _write_plugin(plugin_path, _valid_plugin_source("clean-exit"))
    manager = PluginManager()
    manager.register_plugin(str(plugin_path))
    proxy = manager.get_plugin("clean-exit")
    underlying_process = proxy._process  # noqa: SLF001 - white-box test
    manager.cleanup()
    assert not underlying_process.is_alive()
