"""
Unit tests for ConfigurableWebStrategy.verify_action(strict=...) — بند ۱۳.

These tests use a lightweight mock page instead of real Playwright/Chromium,
so they run without any browser binary and are not skipped in this sandbox.
"""
import asyncio

from atrin_core.provider_strategy import ConfigurableWebStrategy


class _MockLocator:
    def __init__(self, texts: list[str] | None = None, count: int = 0, visible: bool = False):
        self._texts = texts or []
        self._count = count
        self._visible = visible

    async def all_text_contents(self) -> list[str]:
        return self._texts

    async def count(self) -> int:
        return self._count

    @property
    def first(self) -> "_MockLocator":
        return self

    async def is_visible(self) -> bool:
        return self._visible


class _MockPage:
    def __init__(self, *, response_texts: list[str] | None = None,
                 verification_texts: list[str] | None = None,
                 verification_count: int = 0):
        self._response_texts = response_texts or []
        self._verification_texts = verification_texts or []
        self._verification_count = verification_count

    def locator(self, selector: str) -> _MockLocator:
        if selector == "response":
            return _MockLocator(texts=self._response_texts)
        if selector == "verify":
            return _MockLocator(texts=self._verification_texts, count=self._verification_count)
        return _MockLocator()


def _run(coro):
    return asyncio.run(coro)


# ── strict=True, no explicit verification configured ────────────────────────

def test_strict_verification_without_config_returns_false():
    """
    FIX (بند ۱۳): a side-effecting action (strict=True) with NO
    verification_selector and NO verification_text configured must NOT
    be confirmed by mere non-empty completion.
    """
    page = _MockPage(response_texts=["some response text"])
    strategy = ConfigurableWebStrategy(page, config={"response_selector": "response"})

    result = _run(strategy.verify_action("key-1", strict=True))
    assert result is False, \
        "strict verification must refuse to confirm without explicit selector/text config"


def test_non_strict_verification_without_config_falls_back_to_completion():
    """
    Read-only actions (strict=False) may still rely on detect_completion()
    as a best-effort signal — this is the pre-existing, less risky behavior.
    """
    page = _MockPage(response_texts=["some response text"])
    strategy = ConfigurableWebStrategy(page, config={"response_selector": "response"})

    result = _run(strategy.verify_action("key-1", strict=False))
    assert result is True, \
        "non-strict verification should still use detect_completion() as before"


# ── strict=True, explicit verification_text configured ──────────────────────

def test_strict_verification_with_text_config_still_works():
    """
    When verification_text IS configured, strict mode must still confirm
    correctly — strict only removes the *weak* fallback, not explicit config.
    """
    page = _MockPage(response_texts=["Order #12345 confirmed"])
    strategy = ConfigurableWebStrategy(
        page,
        config={"response_selector": "response", "verification_text": "confirmed"},
    )

    result = _run(strategy.verify_action("key-1", strict=True))
    assert result is True


def test_strict_verification_with_text_config_rejects_mismatch():
    page = _MockPage(response_texts=["still processing..."])
    strategy = ConfigurableWebStrategy(
        page,
        config={"response_selector": "response", "verification_text": "confirmed"},
    )

    result = _run(strategy.verify_action("key-1", strict=True))
    assert result is False


# ── strict=True, explicit verification_selector configured ──────────────────

def test_strict_verification_with_selector_config_correlates_identity():
    page = _MockPage(verification_texts=["key-1 operation-1"], verification_count=1)
    strategy = ConfigurableWebStrategy(
        page, config={"verification_selector": "verify"},
    )

    result = _run(strategy.verify_action("key-1", operation_id="operation-1", strict=True))
    assert result is True


def test_strict_verification_with_selector_config_rejects_missing_element():
    page = _MockPage(verification_count=0)
    strategy = ConfigurableWebStrategy(
        page, config={"verification_selector": "verify"},
    )

    result = _run(strategy.verify_action("key-1", strict=True))
    assert result is False


# ── base class default ───────────────────────────────────────────────────────

def test_base_strategy_verify_action_accepts_strict_kwarg():
    """The abstract base's default implementation must accept strict= without TypeError."""
    from atrin_core.provider_strategy import ProviderInteractionStrategy

    class _Minimal(ProviderInteractionStrategy):
        async def detect_login_page(self): return False
        async def locate_composer(self): return None
        async def send_message(self, text): pass
        async def extract_response(self): return ""
        async def detect_auth_challenge(self): return False
        async def detect_completion(self): return False

    strategy = _Minimal(page=None)
    result = _run(strategy.verify_action("key-1", strict=True))
    assert result is False
