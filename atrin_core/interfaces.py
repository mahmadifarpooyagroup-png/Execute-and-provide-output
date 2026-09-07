from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import AuthState


class IProviderAdapter(ABC):
    """Common runtime contract for all provider adapters."""

    @abstractmethod
    async def execute(
        self,
        action: str,
        idempotency_key: str,
        *,
        fencing_token: int | None = None,
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def verify_action(self, idempotency_key: str) -> str:
        raise NotImplementedError

    async def cancel(self, idempotency_key: str) -> bool:
        return False

    async def health(self) -> str:
        return "UNKNOWN"

    async def authenticate(self) -> AuthState:
        return AuthState.UNKNOWN

    def capabilities(self) -> set[str]:
        return set()


class ISessionProvider(ABC):
    @abstractmethod
    async def get_session_state(self, profile_id: str) -> AuthState:
        raise NotImplementedError

    @abstractmethod
    async def acquire_lock(self, profile_id: str, workflow_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    async def renew_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def release_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        raise NotImplementedError
