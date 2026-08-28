from enum import Enum
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class ConnectionKind(str, Enum):
    WEB = "WEB"
    DESKTOP = "DESKTOP"
    API = "API"
    CLI = "CLI"
    LOCAL = "LOCAL"
    REMOTE = "REMOTE"
    MCP = "MCP"
    A2A = "A2A"
    ACP = "ACP"

class AuthState(str, Enum):
    UNKNOWN = "UNKNOWN"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    AUTHENTICATING = "AUTHENTICATING"
    AUTHENTICATED = "AUTHENTICATED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    AUTH_REJECTED = "AUTH_REJECTED"
    AUTH_ERROR = "AUTH_ERROR"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    WAITING_FOR_AUTH = "WAITING_FOR_AUTH"
    WAITING_FOR_HUMAN_INTERACTION = "WAITING_FOR_HUMAN_INTERACTION"

class WorkflowState(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    REPLANNING = "REPLANNING"
    WAITING_FOR_AUTH = "WAITING_FOR_AUTH"
    WAITING_FOR_NETWORK = "WAITING_FOR_NETWORK"
    WAITING_FOR_HUMAN_INTERACTION = "WAITING_FOR_HUMAN_INTERACTION"
    WAITING_FOR_HUMAN_APPROVAL = "WAITING_FOR_HUMAN_APPROVAL"
    WAITING_FOR_PROVIDER = "WAITING_FOR_PROVIDER"
    RECOVERING = "RECOVERING"
    FINALIZING = "FINALIZING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class Step(BaseModel):
    step_id: str
    action: str
    provider_id: str
    idempotency_key: str = ""
    status: str = "PENDING"
    result: Optional[str] = None
    evidence: Optional[str] = None


class Task(BaseModel):
    task_id: str
    description: str
    steps: List[Step] = Field(default_factory=list)
    status: str = "PENDING"

class Provider(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    connection_kind: ConnectionKind
    adapter_id: str
    enabled: bool = True
    priority: int = 10

class ProviderProfile(BaseModel):
    id: str
    provider_id: str
    account_id: str
    name: str
    auth_state: AuthState = AuthState.UNKNOWN
    fencing_token: int = 0

class Session(BaseModel):
    session_id: str
    provider_profile_id: str
    account_id: str
    state: AuthState
    lock_owner: Optional[str] = None
    lease_expiry: Optional[datetime] = None
    fencing_token: int = 0

class IdempotencyRecord(BaseModel):
    idempotency_key: str
    workflow_id: str
    step_id: str
    provider_id: str
    status: str
    created_at: datetime
    confirmed_at: Optional[datetime] = None
