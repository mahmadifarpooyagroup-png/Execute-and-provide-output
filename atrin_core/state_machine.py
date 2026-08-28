from .models import AuthState

STATE_TRANSITIONS = {
    (AuthState.UNKNOWN, "provider_registered"): AuthState.NOT_AUTHENTICATED,
    (AuthState.NOT_AUTHENTICATED, "login_flow_started"): AuthState.LOGIN_REQUIRED,
    (AuthState.LOGIN_REQUIRED, "user_completes_login"): AuthState.AUTHENTICATING,
    (AuthState.AUTHENTICATING, "adapter_confirms_login"): AuthState.AUTHENTICATED,
    (AuthState.AUTHENTICATING, "confirmation_timeout"): AuthState.LOGIN_REQUIRED,
    (AuthState.AUTHENTICATED, "first_action_dispatched"): AuthState.ACTIVE,
    (AuthState.ACTIVE, "action_succeeds"): AuthState.ACTIVE,
    (AuthState.ACTIVE, "idle_timeout_elapsed"): AuthState.AUTHENTICATED,
    (AuthState.ACTIVE, "adapter_detects_logout_marker"): AuthState.EXPIRED,
    (AuthState.EXPIRED, "auto_transition"): AuthState.LOGIN_REQUIRED,
    (AuthState.ACTIVE, "transport_error_no_auth_evidence"): AuthState.NETWORK_UNAVAILABLE,
    (AuthState.NETWORK_UNAVAILABLE, "connectivity_restored_ok"): AuthState.ACTIVE,
    (AuthState.NETWORK_UNAVAILABLE, "connectivity_restored_auth_fail"): AuthState.LOGIN_REQUIRED,
}

def transition_state(current_state: AuthState, event: str) -> AuthState:
    next_state = STATE_TRANSITIONS.get((current_state, event))
    if next_state is None:
        raise ValueError(f"Invalid state transition: {current_state} + {event}")
    return next_state
