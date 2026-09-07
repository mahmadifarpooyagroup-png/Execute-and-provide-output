from abc import ABC, abstractmethod
from typing import Any


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

    async def verify_action(self, idempotency_key: str) -> bool:
        """Return True only when the provider can correlate the requested action with its result."""
        return False
