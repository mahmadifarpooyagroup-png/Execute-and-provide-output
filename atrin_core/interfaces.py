from abc import ABC, abstractmethod
from .models import AuthState

class IProviderAdapter(ABC):
    @abstractmethod
    async def verify_action(self, idempotency_key: str) -> str:
        pass

class ISessionProvider(ABC):
    @abstractmethod
    async def get_session_state(self, profile_id: str) -> AuthState:
        pass
    
    @abstractmethod
    async def acquire_lock(self, profile_id: str, workflow_id: str) -> int:
        pass
