from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class ProviderInteractionStrategy(ABC):
    """Provider-specific DOM behavior used by the vendor-neutral web adapter."""

    def __init__(self, page: Any):
        self.page = page

    @abstractmethod
    async def detect_login_page(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def locate_composer(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def send_message(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def extract_response(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def detect_auth_challenge(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def detect_completion(self) -> bool:
        raise NotImplementedError

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        """Return True only when the provider can correlate the requested action with its result."""
        return False


class ConfigurableWebStrategy(ProviderInteractionStrategy):
    """Generic web strategy driven by selectors instead of vendor-specific code."""

    def __init__(self, page: Any, config: Mapping[str, Any] | None = None):
        super().__init__(page)
        self.config = dict(config or {})

    def _selector(self, name: str, default: str | None = None) -> str | None:
        value = self.config.get(name, default)
        return str(value) if value else None

    async def _visible(self, selector: str | None) -> bool:
        if not selector:
            return False
        return await self.page.locator(selector).first.is_visible()

    async def detect_login_page(self) -> bool:
        return await self._visible(self._selector("login_selector"))

    async def locate_composer(self) -> Any:
        selector = self._selector("composer_selector", "textarea")
        if not selector:
            raise RuntimeError("Generic web provider requires composer_selector")
        locator = self.page.locator(selector).first
        if await locator.count() == 0:
            raise RuntimeError(f"Composer element not found: {selector}")
        return locator

    async def send_message(self, text: str) -> None:
        composer = await self.locate_composer()
        await composer.fill(text)
        send_selector = self._selector("send_selector")
        if send_selector:
            await self.page.locator(send_selector).first.click()
            return
        await composer.press("Enter")

    async def extract_response(self) -> str:
        selector = self._selector("response_selector")
        if not selector:
            return ""
        values = await self.page.locator(selector).all_text_contents()
        return values[-1].strip() if values else ""

    async def detect_auth_challenge(self) -> bool:
        return await self._visible(self._selector("challenge_selector"))

    async def detect_completion(self) -> bool:
        completion_selector = self._selector("completion_selector")
        if completion_selector:
            return await self._visible(completion_selector)
        return bool(await self.extract_response())

    async def verify_action(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        verification_selector = self._selector("verification_selector")
        if verification_selector:
            locator = self.page.locator(verification_selector)
            if await locator.count() == 0:
                return False
            text = "\n".join(await locator.all_text_contents())
            checks = [idempotency_key]
            if operation_id:
                checks.append(operation_id)
            return all(check in text for check in checks)
        verification_text = str(self.config.get("verification_text") or "").strip()
        if verification_text:
            response = await self.extract_response()
            return verification_text in response
        return await self.detect_completion()

    async def cancel_action(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        cancel_selector = self._selector("cancel_selector")
        if not cancel_selector:
            return False
        locator = self.page.locator(cancel_selector).first
        if await locator.count() == 0:
            return False
        await locator.click()
        return True
