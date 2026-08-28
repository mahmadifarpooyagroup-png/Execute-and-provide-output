"""State machine for Atrin AI Control Plane.

Implements the mandatory state transition table per Section 13.1.
"""

from typing import Optional
from .models import AuthState


# Mandatory state transition table per Section 13.1
# (current_state, event) -> new_state
STATE_TRANSITIONS: dict[tuple[AuthState, str], AuthState] = {
    # UNKNOWN -> NOT_AUTHENTICATED on provider_registered
    (AuthState.UNKNOWN, "provider_registered"): AuthState.NOT_AUTHENTICATED,
    
    # NOT_AUTHENTICATED -> LOGIN_REQUIRED on login_flow_started
    (AuthState.NOT_AUTHENTICATED, "login_flow_started"): AuthState.LOGIN_REQUIRED,
    
    # LOGIN_REQUIRED -> AUTHENTICATING on user_completes_login
    (AuthState.LOGIN_REQUIRED, "user_completes_login"): AuthState.AUTHENTICATING,
    
    # AUTHENTICATING -> AUTHENTICATED on adapter_confirms_login (positive evidence)
    (AuthState.AUTHENTICATING, "adapter_confirms_login"): AuthState.AUTHENTICATED,
    
    # AUTHENTICATING -> LOGIN_REQUIRED on confirmation_timeout
    (AuthState.AUTHENTICATING, "confirmation_timeout"): AuthState.LOGIN_REQUIRED,
    
    # AUTHENTICATED -> ACTIVE on first_action_dispatched
    (AuthState.AUTHENTICATED, "first_action_dispatched"): AuthState.ACTIVE,
    
    # ACTIVE -> ACTIVE on action_succeeds
    (AuthState.ACTIVE, "action_succeeds"): AuthState.ACTIVE,
    
    # ACTIVE -> AUTHENTICATED on idle_timeout_elapsed
    (AuthState.ACTIVE, "idle_timeout_elapsed"): AuthState.AUTHENTICATED,
    
    # ACTIVE -> EXPIRED on adapter_detects_logout_marker (positive evidence)
    (AuthState.ACTIVE, "adapter_detects_logout_marker"): AuthState.EXPIRED,
    
    # EXPIRED -> LOGIN_REQUIRED (automatic)
    (AuthState.EXPIRED, "auto_expire"): AuthState.LOGIN_REQUIRED,
    
    # ACTIVE / any -> NETWORK_UNAVAILABLE on transport_error with NO auth evidence
    (AuthState.ACTIVE, "transport_error_no_auth_evidence"): AuthState.NETWORK_UNAVAILABLE,
    (AuthState.NETWORK_UNAVAILABLE, "transport_error_no_auth_evidence"): AuthState.NETWORK_UNAVAILABLE,
    
    # NETWORK_UNAVAILABLE -> ACTIVE on connectivity_restored + session_probe_ok
    (AuthState.NETWORK_UNAVAILABLE, "connectivity_restored_session_ok"): AuthState.ACTIVE,
    
    # NETWORK_UNAVAILABLE -> EXPIRED -> LOGIN_REQUIRED on connectivity_restored + session_probe_fails_with_auth_evidence
    (AuthState.NETWORK_UNAVAILABLE, "connectivity_restored_session_fails_auth"): AuthState.EXPIRED,
    
    # any -> AUTH_REJECTED on provider_rejects_credentials
    (AuthState.UNKNOWN, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.NOT_AUTHENTICATED, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.LOGIN_REQUIRED, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.AUTHENTICATING, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.AUTHENTICATED, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.ACTIVE, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.EXPIRED, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.NETWORK_UNAVAILABLE, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.PROVIDER_UNAVAILABLE, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.AUTH_REJECTED, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    (AuthState.AUTH_ERROR, "provider_rejects_credentials"): AuthState.AUTH_REJECTED,
    
    # any -> AUTH_ERROR on unrecoverable_adapter_auth_error
    (AuthState.UNKNOWN, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.NOT_AUTHENTICATED, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.LOGIN_REQUIRED, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.AUTHENTICATING, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.AUTHENTICATED, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.ACTIVE, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.EXPIRED, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.NETWORK_UNAVAILABLE, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.PROVIDER_UNAVAILABLE, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.AUTH_REJECTED, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
    (AuthState.AUTH_ERROR, "unrecoverable_adapter_auth_error"): AuthState.AUTH_ERROR,
}


def transition_state(current_state: AuthState, event: str) -> AuthState:
    """Transition the state machine based on current state and event.
    
    Args:
        current_state: The current authentication state.
        event: The event triggering the transition.
        
    Returns:
        The new state after the transition.
        
    Raises:
        ValueError: If the transition is not valid per Section 13.1.
    """
    key = (current_state, event)
    
    if key not in STATE_TRANSITIONS:
        raise ValueError(
            f"Invalid state transition: {current_state.value} --[{event}]--> ? "
            f"is not defined in the mandatory state transition table (Section 13.1)"
        )
    
    return STATE_TRANSITIONS[key]
