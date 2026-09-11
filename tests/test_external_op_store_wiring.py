"""
Tests for Phase A fix: ExternalOperationStore wired to A2A/MCP/ACP adapters.

Verifies that after a simulated process restart (fresh adapter instance),
verify_action() can recover the external task ID from the database and
return CONFIRMED instead of AMBIGUOUS.
"""
import asyncio
import tempfile
import os

from atrin_core.database import AtrinDatabase
from atrin_core.external_op_store import ExternalOperationStore
from atrin_core.provider_registry import ProviderAdapterRegistry


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmpdir: str) -> AtrinDatabase:
    return AtrinDatabase(os.path.join(tmpdir, "test.db"))


def _make_registry(adapter_id: str, endpoint: str) -> ProviderAdapterRegistry:
    registry = ProviderAdapterRegistry()
    registry.register({
        "id": f"test-{adapter_id}",
        "name": f"Test {adapter_id.upper()}",
        "adapter_id": adapter_id,
        "endpoint": endpoint,
        "enabled": True,
    })
    return registry


# ── ExternalOperationStore unit tests ─────────────────────────────────────────

def test_external_op_store_record_and_fetch():
    """Store persists and retrieves external operation mapping."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        store = ExternalOperationStore(db)

        store.record(
            idempotency_key="ikey-001",
            workflow_id="wf-001",
            step_id="step-001",
            provider_id="prov-a2a",
            adapter_type="a2a",
            operation_id="op-001",
            external_id="a2a-task-xyz",
            external_status="SUBMITTED",
        )

        row = store.fetch(
            idempotency_key="ikey-001",
            workflow_id="wf-001",
            step_id="step-001",
        )
        assert row is not None
        assert row["external_id"] == "a2a-task-xyz"
        assert row["operation_id"] == "op-001"
        assert row["adapter_type"] == "a2a"


def test_external_op_store_upsert_updates_status():
    """Subsequent record() call updates existing row without duplication."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        store = ExternalOperationStore(db)

        store.record(
            idempotency_key="ikey-002",
            workflow_id="wf-002",
            step_id="step-002",
            provider_id="prov-mcp",
            adapter_type="mcp",
            operation_id="op-002",
            external_id="mcp-call-abc",
            external_status="IN_PROGRESS",
        )
        store.record(
            idempotency_key="ikey-002",
            workflow_id="wf-002",
            step_id="step-002",
            provider_id="prov-mcp",
            adapter_type="mcp",
            operation_id="op-002",
            external_id="mcp-call-abc",
            external_status="CONFIRMED",
        )

        row = store.fetch(
            idempotency_key="ikey-002",
            workflow_id="wf-002",
            step_id="step-002",
        )
        assert row is not None
        assert row["external_status"] == "CONFIRMED"


def test_external_op_store_returns_none_for_missing():
    """fetch() returns None when no record exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        store = ExternalOperationStore(db)

        row = store.fetch(
            idempotency_key="nonexistent",
            workflow_id="wf-x",
            step_id="step-x",
        )
        assert row is None


def test_external_op_store_lookup_by_external_id():
    """fetch_by_external_id() finds record by provider-side task ID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        store = ExternalOperationStore(db)

        store.record(
            idempotency_key="ikey-003",
            workflow_id="wf-003",
            step_id="step-003",
            provider_id="prov-a2a",
            adapter_type="a2a",
            operation_id="op-003",
            external_id="task-provider-999",
        )

        row = store.fetch_by_external_id(
            external_id="task-provider-999",
            provider_id="prov-a2a",
        )
        assert row is not None
        assert row["idempotency_key"] == "ikey-003"


# ── adapter wiring tests ───────────────────────────────────────────────────────

def test_a2a_adapter_store_is_wired_by_registry():
    """
    FIX (بند ۱): after build_adapters(), A2AAdapter._store must not be None.
    This ensures verify_action() can recover external task ID after restart.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        registry = _make_registry("a2a", "http://localhost:9999")
        adapters = registry.build_adapters(db)

        assert "test-a2a" in adapters
        profile_aware = adapters["test-a2a"]

        # Trigger _adapter() creation by accessing the inner adapter
        inner = asyncio.run(_get_inner_adapter(profile_aware, "dummy-key"))
        assert hasattr(inner, "_store"), "A2AAdapter should have _store attribute"
        assert inner._store is not None, \
            "ExternalOperationStore must be wired — was None (restart recovery broken)"


def test_mcp_adapter_store_is_wired_by_registry():
    """FIX (بند ۱): MCPAdapter._store must be wired after build_adapters()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        registry = _make_registry("mcp", "http://localhost:9998/mcp")
        adapters = registry.build_adapters(db)

        inner = asyncio.run(_get_inner_adapter(adapters["test-mcp"], "dummy-key"))
        assert hasattr(inner, "_store")
        assert inner._store is not None, \
            "ExternalOperationStore must be wired to MCPAdapter"


def test_acp_adapter_store_is_wired_by_registry():
    """FIX (بند ۱): ACPAdapter._store must be wired after build_adapters()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        registry = _make_registry("acp", "http://localhost:9997/agent")
        adapters = registry.build_adapters(db)

        inner = asyncio.run(_get_inner_adapter(adapters["test-acp"], "dummy-key"))
        assert hasattr(inner, "_store")
        assert inner._store is not None, \
            "ExternalOperationStore must be wired to ACPAdapter"


async def _get_inner_adapter(profile_aware_adapter, idempotency_key: str):
    """Helper: trigger inner adapter creation and return it."""
    return await profile_aware_adapter._adapter(idempotency_key, None)


# ── restart-survival simulation ────────────────────────────────────────────────

def test_a2a_verify_action_survives_restart_via_store():
    """
    Core correctness test: after a simulated restart (new adapter instance
    with empty memory but the same DB), verify_action() must return CONFIRMED
    by reading the persisted external_id from ExternalOperationStore.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _make_db(tmpdir)
        store = ExternalOperationStore(db)

        # Simulate what the adapter would have stored before the restart
        store.record(
            idempotency_key="ikey-restart-001",
            workflow_id="wf-restart",
            step_id="step-restart",
            provider_id="test-a2a",
            adapter_type="a2a",
            operation_id="op-restart-001",
            external_id="a2a-task-completed-abc",
            external_status="CONFIRMED",
        )

        # After "restart": fresh adapter, empty _last_task_id
        from atrin_core.a2a_adapter import A2AAdapter
        from atrin_core.protocol_models import A2AConfig

        adapter = A2AAdapter(A2AConfig(agent_card_url="http://localhost:9999"))
        adapter._store = store
        adapter._step_context = {
            "workflow_id": "wf-restart",
            "step_id": "step-restart",
        }

        # _last_task_id is empty (fresh process) — must recover from store
        assert adapter._last_task_id is None

        # verify_action must fetch from store and return CONFIRMED
        # (We mock poll_task_status to avoid real HTTP)
        async def mock_poll(task_id: str):
            assert task_id == "a2a-task-completed-abc"
            return {"state": {"status": "completed"}}

        adapter.poll_task_status = mock_poll  # type: ignore[method-assign]

        result = asyncio.run(
            adapter.verify_action("ikey-restart-001", operation_id="op-restart-001")
        )
        assert result == "CONFIRMED", \
            f"Expected CONFIRMED after restart recovery, got {result!r}"
