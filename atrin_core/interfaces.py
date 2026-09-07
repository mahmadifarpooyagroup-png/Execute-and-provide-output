from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import AuthState


class IProviderAdapter(ABC):
    """Common runtime contract shared by every provider adapter."""

    async def execute(
        self,
        action: str,
        idempotency_key: str,
        *,
        operation_id: str | None = None,
        fencing_token: int | None = None,
    ) -> Any:
        raise NotImplementedError("Provider adapter must implement execute()")

    @abstractmethod
    async def verify_action(
        self,
        idempotency_key: str,
        *,
        operation_id: str | None = None,
    ) -> str:
        raise NotImplementedError

    async def cancel(self, idempotency_key: str, *, operation_id: str | None = None) -> bool:
        return False

    async def health(self) -> str:
        return "UNKNOWN"

    async def authenticate(self) -> AuthState:
        return AuthState.UNKNOWN

    def capabilities(self) -> set[str]:
        return set()


class ISessionProvider(ABC):
    @abstractmethod
    def get_session_state(self, profile_id: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def acquire_lock(self, profile_id: str, workflow_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def renew_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def release_lock(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def validate_execution_lease(self, profile_id: str, workflow_id: str, fencing_token: int) -> bool:
        raise NotImplementedError
