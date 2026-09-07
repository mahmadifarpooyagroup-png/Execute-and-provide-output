import sqlite3

import pytest

from atrin_core.database import AtrinDatabase
from atrin_core.plugins.manager import PluginManager
from atrin_core.session_manager import SessionManager


def _valid_plugin_source(plugin_id: str = "regression-plugin") -> str:
    return (
        "from atrin_core.plugins.base import IPlugin\n\n"
        "class RegressionPlugin(IPlugin):\n"
        f"    def get_metadata(self): return {{'plugin_id': '{plugin_id}', 'name': 'Regression Plugin', 'version': '1.0'}}\n"
        "    def initialize(self): return True\n"
        "    def execute(self, action, payload): return {'action': action, 'payload': payload}\n"
        "    def cleanup(self): pass\n"
    )


def test_duplicate_provider_profile_is_rejected(tmp_path):
    database = AtrinDatabase(str(tmp_path / "atrin.db"))
    manager = SessionManager(database)
    manager.create_profile("profile-1", "provider-1", "account-1", "Profile")

    with pytest.raises(sqlite3.IntegrityError):
        manager.create_profile("profile-1", "provider-2", "account-2", "Duplicate")


def test_plugin_deactivation_unloads_worker_and_marks_registry_inactive(tmp_path):
    plugin_path = tmp_path / "plugin.py"
    plugin_path.write_text(_valid_plugin_source(), encoding="utf-8")
    database = AtrinDatabase(str(tmp_path / "atrin.db"))
    manager = PluginManager(database=database)
    manager.register_plugin(str(plugin_path))

    manager.set_active("regression-plugin", False)

    with pytest.raises(KeyError, match="not registered"):
        manager.get_plugin("regression-plugin")

    connection = database.get_connection()
    try:
        row = connection.execute(
            "SELECT is_active FROM plugins_registry WHERE plugin_id=?",
            ("regression-plugin",),
        ).fetchone()
    finally:
        connection.close()

    assert row["is_active"] == 0

    # Re-registration explicitly starts a fresh worker and restores the durable active state.
    assert manager.register_plugin(str(plugin_path)) == "regression-plugin"
    assert manager.get_plugin("regression-plugin").execute("ping", {})["action"] == "ping"
    manager.cleanup()
