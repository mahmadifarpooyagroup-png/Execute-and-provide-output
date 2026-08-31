import json

import pytest

from atrin_core.provider_strategy import ProviderInteractionStrategy
from atrin_core.web_adapter import (
    BrowserMode,
    GenericWebAdapter,
    StaleFencingTokenError,
)


PAGE = "data:text/html,<html><body><input id='composer'><button id='send'>Send</button><div id='response' contenteditable='true' style='display:block;min-height:1em;border:1px solid #ccc;padding:4px;'></div></body></html>"


class FakeStrategy(ProviderInteractionStrategy):
    def __init__(self, page):
        super().__init__(page)
        self.login = False
        self.auth_challenge = False

    async def detect_login_page(self):
        return self.login

    async def locate_composer(self):
        return self.page.locator("#composer")

    async def send_message(self, text):
        await self.page.locator("#composer").fill(text)
        await self.page.locator("#response").text_content()
        await self.page.evaluate("(text) => { document.getElementById('response').textContent = text; }", text)

    async def extract_response(self):
        response = self.page.locator("#response")
        text = await response.text_content()
        return text or ""

    async def detect_auth_challenge(self):
        return self.auth_challenge

    async def detect_completion(self):
        return bool(await self.extract_response())


@pytest.mark.asyncio
async def test_browser_launch_and_message_round_trip(tmp_path):
    adapter = GenericWebAdapter("provider", "profile", FakeStrategy, start_url=PAGE)
    try:
        page = await adapter.launch()
        assert not page.is_closed()
        result = await adapter.execute("hello", "key-1")
        assert result["result"] == "hello"
        evidence = json.loads(result["evidence"])
        assert evidence["response_text"] == "hello"
        assert "composer" in evidence["dom"]
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_persistent_profile_reuse(tmp_path):
    profile_path = str(tmp_path / "provider-profile")
    first = GenericWebAdapter(
        "provider", "profile", FakeStrategy, mode=BrowserMode.PERSISTENT_BROWSER,
        profile_path=profile_path, start_url=PAGE,
    )
    await first.launch()
    await first.page.goto("https://example.com")
    await first.page.evaluate("localStorage.setItem('session', 'persisted')")
    await first.close()

    second = GenericWebAdapter(
        "provider", "profile", FakeStrategy, mode=BrowserMode.PERSISTENT_BROWSER,
        profile_path=profile_path, start_url="https://example.com",
    )
    try:
        await second.launch()
        assert await second.page.evaluate("localStorage.getItem('session')") == "persisted"
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_auth_detection_and_stale_fencing_token(tmp_path):
    current_token = 2
    adapter = GenericWebAdapter(
        "provider", "profile", FakeStrategy, start_url=PAGE,
        profile_path=str(tmp_path / "profile"),
        current_fencing_token=lambda: current_token,
    )
    try:
        await adapter.launch()
        adapter.strategy.login = True
        adapter.strategy.auth_challenge = True
        assert await adapter.detect_login_page() is True
        assert await adapter.detect_auth_challenge() is True
        with pytest.raises(StaleFencingTokenError):
            await adapter.execute("blocked", "key-2", fencing_token=1)
    finally:
        await adapter.close()


def test_cdp_attach_requires_explicit_permission():
    adapter = GenericWebAdapter(
        "provider", "profile", FakeStrategy, mode=BrowserMode.CDP_ATTACH,
        cdp_endpoint="http://127.0.0.1:9222",
    )
    with pytest.raises(PermissionError):
        adapter._validate_cdp_permission()