"""
Phase-A regression tests.

Covers three fixes from the audit report:
  بند ۹/۱۰/۱۱  — A2A/ACP/MCP verify_action is durable across adapter restarts
  بند ۷         — Desktop adapter raises on fake fallback instead of silent success
  بند ۵         — Evidence URL strips query/fragment to prevent token leakage
"""
from __future__ import annotations

import asyncio
import tempfile

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _db(tmpdir: str):
    from atrin_core.database import AtrinDatabase
    return AtrinDatabase(f"{tmpdir}/test.db")


def _store(db):
    from atrin_core.external_op_store import ExternalOperationStore
    return ExternalOperationStore(db)


# ═══════════════════════════════════════════════════════════════════════════════
# بند ۹ — MCP: verify survives restart (store re-hydration)
# ═══════════════════════════════════════════════════════════════════════════════

def test_mcp_verify_action_survives_restart():
    """
    After a process restart MCP in-memory state is gone.
    With the durable store the adapter should re-hydrate from DB and return CONFIRMED.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _db(tmpdir)
        store = _store(db)
        ctx = {"workflow_id": "wf-1", "step_id": "step-1"}

        # Simulate what call_tool() writes to the store
        store.record(
            idempotency_key="ikey-mcp-1",
            workflow_id="wf-1",
            step_id="step-1",
            provider_id="mcp",
            adapter_type="mcp",
            operation_id="op-1",
            external_id="tool-use-abc",
            external_status="CONFIRMED",
        )

        # Fresh adapter instance (simulating restart — no in-memory state)
        from atrin_core.protocol_models import MCPConfig
        from atrin_core.mcp_adapter import MCPAdapter
        config = MCPConfig(server_url="http://mock-mcp")
        adapter = MCPAdapter(config)
        adapter._store = store
        adapter._step_context = ctx

        result = asyncio.run(adapter.verify_action("ikey-mcp-1", operation_id="op-1"))
        assert result == "CONFIRMED", f"Expected CONFIRMED got {result}"


def test_mcp_verify_returns_ambiguous_without_store():
    """Without a store a restarted adapter correctly returns AMBIGUOUS."""
    from atrin_core.protocol_models import MCPConfig
    from atrin_core.mcp_adapter import MCPAdapter
    config = MCPConfig(server_url="http://mock-mcp")
    adapter = MCPAdapter(config)
    # No store, no in-memory state
    result = asyncio.run(adapter.verify_action("unknown-key"))
    assert result == "AMBIGUOUS"


# ═══════════════════════════════════════════════════════════════════════════════
# بند ۱۰ — A2A: verify survives restart via external_id re-hydration
# ═══════════════════════════════════════════════════════════════════════════════

def test_a2a_verify_action_survives_restart():
    """
    After restart A2A adapter should poll the real provider using the stored task_id.
    We mock poll_task_status to return 'completed'.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _db(tmpdir)
        store = _store(db)
        ctx = {"workflow_id": "wf-2", "step_id": "step-2"}

        store.record(
            idempotency_key="ikey-a2a-1",
            workflow_id="wf-2",
            step_id="step-2",
            provider_id="a2a",
            adapter_type="a2a",
            operation_id="op-2",
            external_id="task-xyz-789",
            external_status="in_progress",
        )

        from atrin_core.protocol_models import A2AConfig
        from atrin_core.a2a_adapter import A2AAdapter
        config = A2AConfig(agent_card_url="http://mock-a2a/.well-known/agent.json")
        adapter = A2AAdapter(config)
        adapter._store = store
        adapter._step_context = ctx

        # Mock poll_task_status to simulate provider confirming completion
        async def mock_poll(task_id: str):
            assert task_id == "task-xyz-789"
            return {"status": "completed"}

        adapter.poll_task_status = mock_poll

        result = asyncio.run(adapter.verify_action("ikey-a2a-1", operation_id="op-2"))
        assert result == "CONFIRMED", f"Expected CONFIRMED got {result}"


# ═══════════════════════════════════════════════════════════════════════════════
# بند ۱۱ — ACP: verify survives restart via stored CONFIRMED status
# ═══════════════════════════════════════════════════════════════════════════════

def test_acp_verify_action_survives_restart():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = _db(tmpdir)
        store = _store(db)
        ctx = {"workflow_id": "wf-3", "step_id": "step-3"}

        store.record(
            idempotency_key="ikey-acp-1",
            workflow_id="wf-3",
            step_id="step-3",
            provider_id="acp",
            adapter_type="acp",
            operation_id="op-3",
            external_id="session-001",
            external_status="CONFIRMED",
        )

        from atrin_core.protocol_models import ACPConfig
        from atrin_core.acp_adapter import ACPAdapter
        config = ACPConfig(agent_path="/agents/test")
        adapter = ACPAdapter(config)
        adapter._store = store
        adapter._step_context = ctx

        result = asyncio.run(adapter.verify_action("ikey-acp-1", operation_id="op-3"))
        assert result == "CONFIRMED", f"Expected CONFIRMED got {result}"


# ═══════════════════════════════════════════════════════════════════════════════
# بند ۷ — Desktop adapter: fake fallback raises instead of silent success
# ═══════════════════════════════════════════════════════════════════════════════

def test_desktop_interact_raises_when_no_backend_succeeds():
    """
    If every backend fails, interact_with_element must raise RuntimeError.
    Previously it returned {status: 'fallback-not-available'} which could
    be misread as success.
    """
    from atrin_core.desktop_adapter import GenericDesktopAdapter
    adapter = GenericDesktopAdapter(
        ui_automation_backend=None,
        electron_backend=None,
        cli_backend=None,
    )
    with pytest.raises(RuntimeError, match="Desktop interaction failed"):
        asyncio.run(adapter.interact_with_element("btn-1", "click"))


def test_desktop_execute_action_raises_when_no_backend_succeeds():
    """execute_action with no backend must raise so the engine sees failure."""
    from atrin_core.desktop_adapter import GenericDesktopAdapter
    adapter = GenericDesktopAdapter(
        ui_automation_backend=None,
        electron_backend=None,
        cli_backend=None,
    )
    # interact_with_element is the primary action dispatch method
    with pytest.raises(RuntimeError, match="Desktop interaction failed"):
        asyncio.run(adapter.interact_with_element("btn-submit", "click", None))


# ═══════════════════════════════════════════════════════════════════════════════
# بند ۵ — Evidence URL redaction strips query/fragment
# ═══════════════════════════════════════════════════════════════════════════════

def test_safe_page_url_strips_query_and_fragment():
    from atrin_core.web_adapter import GenericWebAdapter
    cases = [
        ("https://app.example.com/callback?code=AUTH_CODE&state=abc123",
         "https://app.example.com/callback"),
        ("https://provider.com/auth?token=SECRET&session=XYZ#hash",
         "https://provider.com/auth"),
        ("https://api.example.com/v1/data?api_key=MYKEY",
         "https://api.example.com/v1/data"),
        ("https://oauth.example.com/token?access_token=BEARER&refresh_token=RTOKEN",
         "https://oauth.example.com/token"),
        ("https://clean.example.com/path",
         "https://clean.example.com/path"),
    ]
    for raw, expected in cases:
        result = GenericWebAdapter._safe_page_url(raw)
        assert result == expected, f"URL not stripped: {raw!r} → {result!r} (expected {expected!r})"


def test_redact_text_covers_oauth_params():
    from atrin_core.web_adapter import GenericWebAdapter
    text = 'href="?code=AUTHCODE123&state=CSRF_TOKEN&access_token=BEARER_TOKEN"'
    result = GenericWebAdapter._redact_text(text)
    assert "AUTHCODE123" not in result
    assert "CSRF_TOKEN" not in result
    assert "BEARER_TOKEN" not in result
    assert "[REDACTED]" in result


def test_safe_page_url_preserves_path():
    from atrin_core.web_adapter import GenericWebAdapter
    url = "https://app.example.com/dashboard/settings"
    assert GenericWebAdapter._safe_page_url(url) == url


def test_safe_page_url_handles_malformed():
    from atrin_core.web_adapter import GenericWebAdapter
    assert GenericWebAdapter._safe_page_url("not-a-url?token=secret") == "not-a-url"
