"""
Tests for the named, tracked migration framework (بند ۱۸/۲۲).
"""
import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor

from atrin_core.database import AtrinDatabase


def test_fresh_database_records_all_migrations():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = AtrinDatabase(os.path.join(tmpdir, "fresh.db"))
        applied = db.list_applied_migrations()
        ids = {entry["id"] for entry in applied}
        assert "001_idempotency_ledger_recovery_columns" in ids
        assert "002_steps_fencing_and_operation_columns" in ids
        assert "003_checkpoint_revision_column" in ids
        assert "004_workflow_client_request_id_column" in ids
        assert "005_plugins_registry_hash_columns" in ids
        assert "006_sync_metadata_last_known_remote_revision" in ids
        assert "007_backfill_and_repair_ids" in ids
        assert "008_core_indexes" in ids
        assert all(entry["applied_at"] for entry in applied)


def test_migrations_are_not_reapplied_on_reopen():
    """Opening the same database twice must not duplicate migration records."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "reopen.db")
        AtrinDatabase(db_path)
        first_count = len(AtrinDatabase(db_path).list_applied_migrations())
        second_count = len(AtrinDatabase(db_path).list_applied_migrations())
        assert first_count == second_count
        db = AtrinDatabase(db_path)
        ids = [entry["id"] for entry in db.list_applied_migrations()]
        assert len(ids) == len(set(ids))


def test_pre_existing_database_without_migrations_table_is_backfilled():
    """
    FIX (بند ۱۸/۲۲): simulate a database created before schema_migrations
    existed, but whose additive schema changes have already been applied.
    Reopening with the new framework must record all migrations without
    attempting destructive or duplicate schema changes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "legacy.db")

        legacy_db = AtrinDatabase(db_path)
        conn = legacy_db.get_connection()
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
        conn.commit()
        conn.close()

        raw = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "schema_migrations" not in tables
        raw.close()

        reopened = AtrinDatabase(db_path)
        applied = reopened.list_applied_migrations()
        assert len(applied) == 8
        assert len({entry["id"] for entry in applied}) == 8


def test_migration_framework_does_not_break_existing_data():
    """Backfilling migrations for a pre-populated database must not touch existing rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "data.db")
        db = AtrinDatabase(db_path)
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO workflows (workflow_id, goal, state) VALUES (?, ?, ?)",
            ("wf-1", "test goal", "IDLE"),
        )
        conn.commit()
        conn.close()

        db2 = AtrinDatabase(db_path)
        conn2 = db2.get_connection()
        row = conn2.execute(
            "SELECT goal, state FROM workflows WHERE workflow_id=?", ("wf-1",)
        ).fetchone()
        conn2.close()
        assert row is not None
        assert row["goal"] == "test goal"
        assert row["state"] == "IDLE"


def test_schema_version_metadata_still_maintained():
    """schema_metadata.schema_version must remain maintained alongside the ledger."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = AtrinDatabase(os.path.join(tmpdir, "version.db"))
        conn = db.get_connection()
        row = conn.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert int(row["value"]) == AtrinDatabase.CURRENT_SCHEMA_VERSION


def test_concurrent_database_initialization_serializes_migrations():
    """
    Multiple real threads opening the same new SQLite database concurrently
    must serialize schema creation/migration and leave one complete migration
    ledger. This guards the migration framework's exactly-once claim under
    genuine contention rather than only sequential re-open tests.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "concurrent.db")

        def open_database() -> int:
            return len(AtrinDatabase(db_path).list_applied_migrations())

        with ThreadPoolExecutor(max_workers=8) as executor:
            counts = list(executor.map(lambda _: open_database(), range(8)))

        assert counts == [8] * 8
        db = AtrinDatabase(db_path)
        applied = db.list_applied_migrations()
        assert len(applied) == 8
        assert len({entry["id"] for entry in applied}) == 8
