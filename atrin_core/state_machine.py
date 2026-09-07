from __future__ import annotations

from .models import AuthState, WorkflowState


AUTH_TRANSITIONS = {
    (AuthState.UNKNOWN.value, "provider_registered"): AuthState.NOT_AUTHENTICATED,
    (AuthState.NOT_AUTHENTICATED.value, "login_flow_started"): AuthState.LOGIN_REQUIRED,
    (AuthState.LOGIN_REQUIRED.value, "user_completes_login"): AuthState.AUTHENTICATING,
    (AuthState.AUTHENTICATING.value, "adapter_confirms_login"): AuthState.AUTHENTICATED,
    (AuthState.AUTHENTICATING.value, "confirmation_timeout"): AuthState.LOGIN_REQUIRED,
    (AuthState.AUTHENTICATED.value, "first_action_dispatched"): AuthState.ACTIVE,
    (AuthState.ACTIVE.value, "action_succeeds"): AuthState.ACTIVE,
    (AuthState.ACTIVE.value, "idle_timeout_elapsed"): AuthState.AUTHENTICATED,
    (AuthState.ACTIVE.value, "adapter_detects_logout_marker"): AuthState.EXPIRED,
    (AuthState.EXPIRED.value, "auto_transition"): AuthState.LOGIN_REQUIRED,
    (AuthState.ACTIVE.value, "transport_error_no_auth_evidence"): AuthState.NETWORK_UNAVAILABLE,
    (AuthState.NETWORK_UNAVAILABLE.value, "connectivity_restored_ok"): AuthState.ACTIVE,
    (AuthState.NETWORK_UNAVAILABLE.value, "connectivity_restored_auth_fail"): AuthState.LOGIN_REQUIRED,
}

WORKFLOW_TRANSITIONS: dict[str, set[str]] = {
    WorkflowState.IDLE.value: {
        WorkflowState.PLANNING.value,
        WorkflowState.PLAN_READY.value,
        WorkflowState.EXECUTING.value,
        WorkflowState.WAITING_FOR_AUTH.value,
        WorkflowState.WAITING_FOR_NETWORK.value,
        WorkflowState.WAITING_FOR_HUMAN_INTERACTION.value,
        WorkflowState.WAITING_FOR_HUMAN_APPROVAL.value,
        WorkflowState.WAITING_FOR_PROVIDER.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.PLANNING.value: {
        WorkflowState.PLAN_READY.value,
        WorkflowState.REJECTED.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.PLAN_READY.value: {
        WorkflowState.EXECUTING.value,
        WorkflowState.REJECTED.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.EXECUTING.value: {
        WorkflowState.OBSERVING.value,
        WorkflowState.VERIFYING.value,
        WorkflowState.WAITING_FOR_AUTH.value,
        WorkflowState.WAITING_FOR_NETWORK.value,
        WorkflowState.WAITING_FOR_HUMAN_INTERACTION.value,
        WorkflowState.WAITING_FOR_HUMAN_APPROVAL.value,
        WorkflowState.WAITING_FOR_PROVIDER.value,
        WorkflowState.RECOVERING.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
    },
    WorkflowState.OBSERVING.value: {
        WorkflowState.VERIFYING.value,
        WorkflowState.EXECUTING.value,
        WorkflowState.WAITING_FOR_PROVIDER.value,
        WorkflowState.RECOVERING.value,
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
        WorkflowState.CANCELLING.value,
    },
    WorkflowState.VERIFYING.value: {
        WorkflowState.OBSERVING.value,
        WorkflowState.EXECUTING.value,
        WorkflowState.WAITING_FOR_PROVIDER.value,
        WorkflowState.RECOVERING.value,
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
        WorkflowState.CANCELLING.value,
    },
    WorkflowState.REPLANNING.value: {
        WorkflowState.PLAN_READY.value,
        WorkflowState.EXECUTING.value,
        WorkflowState.REJECTED.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.WAITING_FOR_AUTH.value: {
        WorkflowState.RECOVERING.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.WAITING_FOR_NETWORK.value: {
        WorkflowState.RECOVERING.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.WAITING_FOR_HUMAN_INTERACTION.value: {
        WorkflowState.RECOVERING.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.WAITING_FOR_HUMAN_APPROVAL.value: {
        WorkflowState.RECOVERING.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
        WorkflowState.REJECTED.value,
    },
    WorkflowState.WAITING_FOR_PROVIDER.value: {
        WorkflowState.RECOVERING.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.RECOVERING.value: {
        WorkflowState.EXECUTING.value,
        WorkflowState.VERIFYING.value,
        WorkflowState.WAITING_FOR_AUTH.value,
        WorkflowState.WAITING_FOR_NETWORK.value,
        WorkflowState.WAITING_FOR_PROVIDER.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
        WorkflowState.CANCELLED.value,
    },
    WorkflowState.CANCELLING.value: {
        WorkflowState.CANCELLED.value,
        WorkflowState.WAITING_FOR_PROVIDER.value,
    },
    WorkflowState.FINALIZING.value: {
        WorkflowState.REPORTING.value,
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
    },
    WorkflowState.REPORTING.value: {
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
    },
    WorkflowState.COMPLETED.value: set(),
    WorkflowState.REJECTED.value: set(),
    WorkflowState.CANCELLED.value: set(),
    WorkflowState.FAILED.value: {
        WorkflowState.RECOVERING.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
    },
}


def transition_auth_state(current: AuthState | str, event: str) -> AuthState:
    current_value = current.value if isinstance(current, AuthState) else current
    try:
        return AUTH_TRANSITIONS[(current_value, event)]
    except KeyError as error:
        raise ValueError(f"Invalid auth transition: {current_value} --{event}--> ?") from error


def can_transition_workflow(current: WorkflowState | str, target: WorkflowState | str) -> bool:
    current_value = current.value if isinstance(current, WorkflowState) else current
    target_value = target.value if isinstance(target, WorkflowState) else target
    return target_value in WORKFLOW_TRANSITIONS.get(current_value, set())


def assert_workflow_transition(current: WorkflowState | str, target: WorkflowState | str) -> None:
    if not can_transition_workflow(current, target):
        current_value = current.value if isinstance(current, WorkflowState) else current
        target_value = target.value if isinstance(target, WorkflowState) else target
        raise ValueError(f"Invalid workflow transition: {current_value} -> {target_value}")


def transition_state(current: AuthState, event: str) -> AuthState:
    """Backward-compatible authentication transition alias."""
    return transition_auth_state(current, event)
