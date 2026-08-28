"""Core interfaces for Atrin AI Control Plane."""

from abc import ABC, abstractmethod
from typing import Optional, Any
from .models import AuthState


class IProviderAdapter(ABC):
    """Abstract base class for provider adapters.
    
    Per Section 35.2, every adapter must implement verify_action.
    """
    
    @abstractmethod
    def verify_action(self, idempotency_key: str) -> str:
        """Verify the status of an action by idempotency key.
        
        Returns one of: NOT_STARTED | IN_PROGRESS | CONFIRMED | FAILED
        
        Per Section 35.2, this contract must be implemented by all adapters
        (Web, Desktop, CLI, API, MCP, A2A, ACP).
        """
        pass


class ISessionProvider(ABC):
    """Abstract base class for session providers.
    
    Per Section 20, handles session lease/lock operations.
    """
    
    @abstractmethod
    def acquire_lock(
        self,
        profile_id: str,
        workflow_id: str,
        owner_id: str,
        lease_duration_seconds: int = 300
    ) -> tuple[bool, int]:
        """Acquire a lock on a provider profile.
        
        Args:
            profile_id: The provider profile ID to lock.
            workflow_id: The workflow requesting the lock.
            owner_id: The owner/requester ID.
            lease_duration_seconds: Duration of the lease in seconds.
            
        Returns:
            Tuple of (success, fencing_token).
            fencing_token is incremented on each successful acquisition.
        """
        pass
    
    @abstractmethod
    def get_session_state(self, session_id: str) -> Optional[AuthState]:
        """Get the current authentication state of a session.
        
        Args:
            session_id: The session ID to query.
            
        Returns:
            The current AuthState, or None if session not found.
        """
        pass
