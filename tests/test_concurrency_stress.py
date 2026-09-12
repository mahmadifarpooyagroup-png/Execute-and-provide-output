"""
Concurrency stress tests (فاز C).

These reuse the real SQLite-backed WorkflowEngine/SessionManager (WAL mode
+ busy_timeout=5000, configured in database.py) and drive genuine
concurrent asyncio tasks against them — not mocks — to prove the race
guards added earlier in this audit (CANCELLING admission block, lease
ownership checks, atomic idempotency claims) actually hold under
contention, not just in single-threaded sequential tests.
"""
import asyncio
import os
import tempfile

import pytest

from atrin_core.database import AtrinDatabase
from atrin_core.models import Step, Task, WorkflowState
from atrin_core.session_manager import SessionManager
from atrin_core.workflow_engine import WorkflowEngine


class SlowAdapter:
    """An adapter whose execute() takes a moment, widening the race window."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.execute_calls = 0

    async def execute(self, action, idempotency_key, *, operation_id=None, fencing_token=None):
        self.execute_calls += 1
        await asyncio.sleep(self.delay)
        return {"result": "ok", "evidence": "receipt"}

    async def verify_action(self, idempotency_key, *, operation_id=None):
        return "CONFIRMED"

    async def cancel(self, idempotency_key, *, operation_id=None):
        return True


def _build_engine(adapter=None, protected=False):
    tmpdir = tempfile.TemporaryDirectory()
    database = AtrinDatabase(os.path.join(tmpdir.name, "workflow.db"))
    adapter = adapter or SlowAdapter()
    session_manager = SessionManager(database) if protected else None
    engine = WorkflowEngine(database, {"provider-a": adapter}, session_manager=session_manager)
    return tmpdir, database, engine, adapter


def _make_workflow(engine, key="key-1", protected=False):
    return engine.create_workflow(
        "ship",
        [Task(task_id="task-1", description="do", steps=[
            Step(step_id="step-1", action="write", provider_id="provider-a", idempotency_key=key,
                 provider_profile_id="profile-1" if protected else None, side_effecting=protected)
        ])],
    )


# ── execute vs cancel race ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_during_execute_does_not_corrupt_state():
    """
    Start execute_step() (slow adapter widens the window), then immediately
    race cancel_workflow() against it. Whichever wins, the final workflow
    state must be a legal, self-consistent terminal-or-executing state —
    never left in an ambiguous or illegally-transitioned state, and the
    CANCELLING admission guard (بند ۳) must never allow a SECOND concurrent
    execute_step() to start once cancellation has begun.
    """
    tmpdir, database, engine, adapter = _build_engine(adapter=SlowAdapter(delay=0.1))
    try:
        workflow_id = _make_workflow(engine)

        async def run_execute():
            try:
                return await engine.execute_step(workflow_id, "step-1")
            except (RuntimeError, LookupError) as error:
                return error

        async def run_cancel():
            await asyncio.sleep(0.02)  # let execute_step begin first
            try:
                await engine.cancel_workflow(workflow_id)
            except RuntimeError:
                pass

        # A second execute_step attempt started AFTER cancel should always
        # be rejected once the workflow has moved to CANCELLING/CANCELLED.
        async def run_second_execute_after_cancel():
            await asyncio.sleep(0.15)  # after cancel_workflow should have run
            try:
                await engine.execute_step(workflow_id, "step-1")
                return "allowed"
            except RuntimeError:
                return "blocked"

        _, _, second_attempt_result = await asyncio.gather(
            run_execute(), run_cancel(), run_second_execute_after_cancel(),
        )

        final_state = engine.get_workflow_state(workflow_id)
        assert final_state in {
            WorkflowState.CANCELLED, WorkflowState.CANCELLING,
            WorkflowState.OBSERVING, WorkflowState.COMPLETED, WorkflowState.RECOVERING,
        }, f"workflow left in unexpected state: {final_state}"

        # The adapter must not have been invoked twice concurrently in a
        # way that duplicates the side effect for the same idempotency key —
        # at most one successful dispatch for step-1's single idempotency key.
        assert adapter.execute_calls <= 1, \
            f"adapter.execute() called {adapter.execute_calls} times — possible duplicate side effect"

        # If cancellation had already taken effect, the racing second
        # execute attempt must have been blocked, not silently allowed.
        if final_state in {WorkflowState.CANCELLED, WorkflowState.CANCELLING}:
            assert second_attempt_result == "blocked"
    finally:
        tmpdir.cleanup()


# ── two workers claiming the same step ───────────────────────────────────────

@pytest.mark.asyncio
async def test_two_concurrent_workers_claiming_same_step_only_one_executes():
    """
    Four 'workers' (concurrent asyncio tasks) call execute_step() for the
    SAME step_id at the same time. The idempotency ledger's atomic INSERT/
    UPDATE claim must ensure only one of them actually dispatches the
    side-effecting action — the other must either receive the same
    already-confirmed result or a clean rejection, never a second
    independent dispatch.
    """
    tmpdir, database, engine, adapter = _build_engine(adapter=SlowAdapter(delay=0.08))
    try:
        workflow_id = _make_workflow(engine)

        async def worker():
            try:
                return await engine.execute_step(workflow_id, "step-1")
            except Exception as error:  # noqa: BLE001 - we want to inspect any outcome
                return error

        results = await asyncio.gather(worker(), worker(), worker(), worker())

        # Regardless of how many callers raced in, the underlying adapter
        # must have been dispatched at most once for this idempotency key.
        assert adapter.execute_calls <= 1, \
            f"adapter.execute() called {adapter.execute_calls} times for one idempotency key — duplicate side effect"

        successes = [r for r in results if isinstance(r, dict)]
        assert len(successes) >= 1, "at least one concurrent worker should have obtained the result"
    finally:
        tmpdir.cleanup()


# ── session lease: renew vs expire vs steal ──────────────────────────────────

def test_concurrent_lease_acquisition_only_one_owner_at_a_time():
    """
    Two 'workflows' race to acquire the same provider profile's lease.
    Exactly one must win while the lease is live; the other must be
    rejected with RuntimeError (بند ۶ — acquire_lock ownership semantics).
    """
    tmpdir = tempfile.TemporaryDirectory()
    try:
        database = AtrinDatabase(os.path.join(tmpdir.name, "session.db"))
        manager = SessionManager(database)
        manager.create_profile("profile-1", "provider-a", "acct-1", "Test Profile")

        results: list[object] = []

        def try_acquire(owner: str):
            try:
                token = manager.acquire_lock("profile-1", owner)
                results.append(("ok", owner, token))
            except RuntimeError as error:
                results.append(("blocked", owner, str(error)))

        import threading
        threads = [threading.Thread(target=try_acquire, args=(f"workflow-{i}",)) for i in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        winners = [r for r in results if r[0] == "ok"]
        blocked = [r for r in results if r[0] == "blocked"]
        # Exactly one thread should have won the lock (all racing at once,
        # no prior owner) — the rest must be cleanly blocked.
        assert len(winners) == 1, f"expected exactly 1 winner, got {len(winners)}: {results}"
        assert len(blocked) == 4
    finally:
        tmpdir.cleanup()


def test_renew_lock_rejected_for_non_owner_during_concurrent_access():
    """
    While workflow-A holds a live lease, a concurrent renew_lock() attempt
    by workflow-B (which never acquired it) must always be rejected —
    never silently succeed due to a race in the read-then-write sequence.
    """
    tmpdir = tempfile.TemporaryDirectory()
    try:
        database = AtrinDatabase(os.path.join(tmpdir.name, "session.db"))
        manager = SessionManager(database)
        manager.create_profile("profile-1", "provider-a", "acct-1", "Test Profile")
        token = manager.acquire_lock("profile-1", "workflow-A")

        results: list[bool] = []

        def try_renew_as_stranger():
            results.append(manager.renew_lock("profile-1", "workflow-B", token))

        import threading
        threads = [threading.Thread(target=try_renew_as_stranger) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert all(result is False for result in results), \
            f"a non-owner renew_lock() succeeded under concurrency: {results}"

        # The true owner's renewal must still work afterward.
        assert manager.renew_lock("profile-1", "workflow-A", token) is True
    finally:
        tmpdir.cleanup()


# ── two workers updating the same workflow's state concurrently ─────────────

def test_concurrent_checkpoint_writes_are_serialized_not_corrupted():
    """
    Several threads write checkpoints for the same workflow_id concurrently
    via WorkflowEngine.save(). Thanks to WAL + busy_timeout, every write
    must either succeed or raise a clear sqlite3 error — never silently
    corrupt or interleave partial JSON payloads.
    """
    tmpdir, database, engine, _ = _build_engine()
    try:
        workflow_id = _make_workflow(engine)
        errors: list[Exception] = []

        def write_checkpoint(index: int):
            try:
                asyncio.run(engine.save(workflow_id, {
                    "workflow_id": workflow_id,
                    "state": "EXECUTING",
                    "marker": index,
                    "checkpoint_version": 1,
                }))
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        import threading
        threads = [threading.Thread(target=write_checkpoint, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        # WAL + busy_timeout should let all writes succeed serialized —
        # if any error occurred it must be a clean sqlite3 error, not a
        # hang or silent corruption.
        for error in errors:
            assert "database" in str(error).lower() or "locked" in str(error).lower()

        final = asyncio.run(engine.load(workflow_id))
        assert final is not None
        assert isinstance(final.get("marker"), int)  # a valid, uncorrupted final write
    finally:
        tmpdir.cleanup()
