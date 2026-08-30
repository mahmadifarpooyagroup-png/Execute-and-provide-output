from abc import ABC, abstractmethod
from typing import Any


class ProviderInteractionStrategy(ABC):
    """Provider-specific DOM behavior used by the vendor-neutral web adapter."""

    def __init__(self, page: Any):
        self.page = page

    @abstractmethod
    async def detect_login_page(self) -> bool:
        pass

    @abstractmethod
    async def locate_composer(self) -> Any:
        pass

    @abstractmethod
    async def send_message(self, text: str) -> None:
        pass

    @abstractmethod
    async def extract_response(self) -> str:
        pass

    @abstractmethod
    async def detect_auth_challenge(self) -> bool:
        pass

    @abstractmethod
    async def detect_completion(self) -> bool:
        pass