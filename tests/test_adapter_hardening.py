import asyncio
from unittest.mock import AsyncMock

from atrin_core.mcp_adapter import MCPAdapter
from atrin_core.protocol_models import MCPConfig
from atrin_core.web_adapter import GenericWebAdapter


def test_mcp_structured_action_separates_tool_and_arguments():
    adapter = MCPAdapter(MCPConfig(server_url="https://example.invalid"))
    assert adapter._resolve_tool_action('{"tool":"send_email","arguments":{"to":"a@example.com"}}') == (
        "send_email",
        {"to": "a@example.com"},
    )


def test_mcp_default_tool_supports_plain_action_text():
    adapter = MCPAdapter(MCPConfig(
        server_url="https://example.invalid",
        default_tool="search",
        default_arguments={"limit": 5},
    ))
    assert adapter._resolve_tool_action("find recent messages") == ("search", {"limit": 5})


def test_web_safe_url_removes_credentials_query_and_fragment():
    assert GenericWebAdapter._safe_page_url(
        "https://user:password@example.com:8443/a?token=secret&state=x#fragment"
    ) == "https://example.com:8443/a"


def test_web_evidence_redacts_response_text_and_safe_url():
    adapter = GenericWebAdapter("provider", "profile", lambda page: None)  # type: ignore[arg-type]
    strategy = type("Strategy", (), {})()
    strategy.extract_response = AsyncMock(return_value="token=super-secret")
    adapter.strategy = strategy
    page = type("Page", (), {"url": "https://example.com/?token=super-secret", "is_closed": lambda self: False})()
    page.title = AsyncMock(return_value="Test")
    page.evaluate = AsyncMock(return_value="<main>hello</main>")
    adapter.page = page

    evidence = asyncio.run(adapter.capture_evidence())
    assert evidence["response_text"] == "token=[REDACTED]"
    assert evidence["page_state"]["url"] == "https://example.com/"
