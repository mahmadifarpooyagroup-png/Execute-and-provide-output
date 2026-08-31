import asyncio
import json
from enum import Enum
from typing import Any, Callable, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .interfaces import IProviderAdapter
from .profile_paths import get_browser_profile_path
from .provider_strategy import ProviderInteractionStrategy


class BrowserMode(str, Enum):
    MANAGED_NEW_BROWSER = "MANAGED_NEW_BROWSER"
    PERSISTENT_BROWSER = "PERSISTENT_BROWSER"
    CDP_ATTACH = "CDP_ATTACH"


class StaleFencingTokenError(RuntimeError):
    """Raised when an action arrives from a superseded profile lock holder."""


class GenericWebAdapter(IProviderAdapter):
    """Playwright transport shared by web providers.

    Provider selectors and response semantics remain in ``strategy``.
    """

    def __init__(
        self,
        provider_id: str,
        profile_id: str,
        strategy_factory: Callable[[Page], ProviderInteractionStrategy],
        *,
        mode: BrowserMode = BrowserMode.MANAGED_NEW_BROWSER,
        start_url: Optional[str] = None,
        profile_path: Optional[str] = None,
        browser_name: str = "chromium",
        headless: bool = True,
        cdp_endpoint: Optional[str] = None,
        allow_cdp_attach: bool = False,
        fencing_token: Optional[int] = None,
        current_fencing_token: Optional[Callable[[], int]] = None,
        completion_timeout: float = 30.0,
    ):
        self.provider_id = provider_id
        self.profile_id = profile_id
        self.strategy_factory = strategy_factory
        self.mode = BrowserMode(mode)
        self.start_url = start_url
        self.profile_path = profile_path or get_browser_profile_path(provider_id, profile_id)
        self.browser_name = browser_name
        self.headless = headless
        self.cdp_endpoint = cdp_endpoint
        self.allow_cdp_attach = allow_cdp_attach
        self.fencing_token = fencing_token
        self.current_fencing_token = current_fencing_token
        self.completion_timeout = completion_timeout
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.strategy: Optional[ProviderInteractionStrategy] = None
        self._owns_browser = False

    async def launch(self, url: Optional[str] = None) -> Page:
        if self.page and not self.page.is_closed():
            return self.page
        self.playwright = await async_playwright().start()
        if self.mode == BrowserMode.CDP_ATTACH:
            self._validate_cdp_permission()
            if not self.cdp_endpoint:
                raise ValueError("cdp_endpoint is required for CDP_ATTACH")
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_endpoint)
            self._owns_browser = False
            self.context, self.page = self._select_attached_page(url or self.start_url)
        elif self.mode == BrowserMode.PERSISTENT_BROWSER:
            browser_type = getattr(self.playwright, self.browser_name)
            self.context = await browser_type.launch_persistent_context(
                self.profile_path, headless=self.headless
            )
            self._owns_browser = True
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        else:
            browser_type = getattr(self.playwright, self.browser_name)
            self.browser = await browser_type.launch(headless=self.headless)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
            self._owns_browser = True
        self.strategy = self.strategy_factory(self.page)
        target_url = url or self.start_url
        if target_url:
            if target_url.startswith("data:"):
                await self.page.set_content(target_url[len("data:text/html,"):])
                await self.page.evaluate(
                    """
                    () => {
                        const response = document.getElementById('response');
                        if (response) {
                            response.setAttribute('contenteditable', 'true');
                            response.style.display = 'block';
                            response.style.minHeight = '1em';
                            response.style.border = '1px solid #ccc';
                            response.style.padding = '4px';
                        }
                    }
                    """
                )
            else:
                await self.page.goto(target_url)
        return self.page

    async def attach(self, cdp_endpoint: str, *, target_url: Optional[str] = None) -> Page:
        self.mode = BrowserMode.CDP_ATTACH
        self.cdp_endpoint = cdp_endpoint
        return await self.launch(target_url)

    async def close(self) -> None:
        if self.context and self._owns_browser:
            await self.context.close()
        elif self.browser and self._owns_browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.playwright = self.browser = self.context = self.page = self.strategy = None
        self._owns_browser = False

    async def detect_login_page(self) -> bool:
        strategy = await self._ready()
        return await strategy.detect_login_page()

    async def detect_auth_challenge(self) -> bool:
        strategy = await self._ready()
        return await strategy.detect_auth_challenge()

    async def capture_evidence(self, *, screenshot: bool = False) -> dict[str, Any]:
        await self._ready()
        assert self.page is not None
        evidence: dict[str, Any] = {
            "response_text": await self.strategy.extract_response(),  # type: ignore[union-attr]
            "page_state": {"url": self.page.url, "title": await self.page.title()},
            "dom": await self.page.evaluate("() => document.body.innerHTML"),
        }
        if screenshot:
            evidence["screenshot"] = await self.page.screenshot(encoding="base64")
        return evidence

    async def execute(self, action: str, idempotency_key: str, *, fencing_token: Optional[int] = None) -> dict[str, Any]:
        self._check_fencing_token(fencing_token)
        strategy = await self._ready()
        await strategy.send_message(action)
        deadline = asyncio.get_running_loop().time() + self.completion_timeout
        while not await strategy.detect_completion():
            if await strategy.detect_auth_challenge():
                raise RuntimeError("provider authentication challenge detected")
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("provider response did not complete")
            await asyncio.sleep(0.1)
        evidence = await self.capture_evidence()
        return {"result": evidence["response_text"], "evidence": json.dumps(evidence)}

    async def verify_action(self, idempotency_key: str) -> str:
        await self._ready()
        if await self.strategy.detect_auth_challenge():  # type: ignore[union-attr]
            return "AUTH_REQUIRED"
        return "CONFIRMED" if await self.strategy.detect_completion() else "NOT_STARTED"  # type: ignore[union-attr]

    async def _ready(self) -> ProviderInteractionStrategy:
        if not self.strategy or not self.page or self.page.is_closed():
            await self.launch()
        assert self.strategy is not None
        return self.strategy

    def _check_fencing_token(self, supplied: Optional[int]) -> None:
        if supplied is None or self.current_fencing_token is None:
            return
        current = self.current_fencing_token()
        if supplied < current:
            raise StaleFencingTokenError(
                f"stale fencing token {supplied}; current token is {current}"
            )

    def _validate_cdp_permission(self) -> None:
        if not self.allow_cdp_attach:
            raise PermissionError("CDP_ATTACH requires explicit allow_cdp_attach=True")

    def _select_attached_page(self, target_url: Optional[str]) -> tuple[BrowserContext, Page]:
        assert self.browser is not None
        contexts = self.browser.contexts
        if not contexts:
            raise RuntimeError("attached browser has no context")
        context = contexts[0]
        pages = context.pages
        if target_url:
            for page in pages:
                if page.url == target_url or page.url.startswith(target_url):
                    return context, page
            raise RuntimeError(f"attached target page not found: {target_url}")
        if len(pages) != 1:
            raise ValueError("CDP_ATTACH requires target_url when multiple pages are open")
        return context, pages[0]