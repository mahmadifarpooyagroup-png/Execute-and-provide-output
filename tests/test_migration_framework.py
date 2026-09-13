"""
Tests for the named, tracked migration framework (بند ۱۸/۲۲).
"""
import os
import sqlite3
import tempfile

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
        # every entry has a real applied_at timestamp
        assert all(entry["applied_at"] for entry in applied)


def test_migrations_are_not_reapplied_on_reopen():
    """Opening the same database twice must not duplicate migration records."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "reopen.db")
        AtrinDatabase(db_path)
        first_count = len(AtrinDatabase(db_path).list_applied_migrations())
        second_count = len(AtrinDatabase(db_path).list_applied_migrations())
        assert first_count == second_count
        # Confirm no duplicate IDs
        db = AtrinDatabase(db_path)
        ids = [entry["id"] for entry in db.list_applied_migrations()]
        assert len(ids) == len(set(ids))


def test_pre_existing_database_without_migrations_table_is_backfilled():
    """
    FIX (بند ۱۸/۲۲) — backward compatibility test: simulate a database that
    was created by an OLDER version of this code, before schema_migrations
    existed but where the columns it would have added already exist
    (because the old additive _add_column_if_missing logic already ran).
    Opening it with the NEW code must retroactively record every migration
    as applied, without attempting to re-run (or erroring on) already-applied
    schema changes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "legacy.db")

        # Build a "legacy" database: full current schema and columns, but
        # deliberately WITHOUT ever creating schema_migrations — simulating
        # a database from before this framework was introduced.
        legacy_db = AtrinDatabase(db_path)
        conn = legacy_db.get_connection()
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
        conn.commit()
        conn.close()

        # Verify our simulation: no migrations table right now
        raw = sqlite3.connect(db_path)
        tables = {row[0] for row in raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "schema_migrations" not in tables
        raw.close()

        # Re-opening with AtrinDatabase must recreate schema_migrations and
        # backfill it — no exception, and every migration ends up recorded.
        reopened = AtrinDatabase(db_path)
        applied = reopened.list_applied_migrations()
        assert len(applied) == 8


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

        # Re-open (triggers _migrate again, idempotently)
        db2 = AtrinDatabase(db_path)
        conn2 = db2.get_connection()
        row = conn2.execute("SELECT goal, state FROM workflows WHERE workflow_id=?", ("wf-1",)).fetchone()
        conn2.close()
        assert row is not None
        assert row["goal"] == "test goal"
        assert row["state"] == "IDLE"


def test_schema_version_metadata_still_maintained():
    """The existing schema_metadata.schema_version mechanism must still work alongside the new ledger."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = AtrinDatabase(os.path.join(tmpdir, "version.db"))
        conn = db.get_connection()
        row = conn.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()
        conn.close()
        assert row is not None
        assert int(row["value"]) == AtrinDatabase.CURRENT_SCHEMA_VERSION
