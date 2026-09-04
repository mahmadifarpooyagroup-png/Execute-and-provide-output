from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional
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
    roles: List[str] = Field(default_factory=list)
    connection_kind: ConnectionKind = ConnectionKind.API
    transport: Optional[str] = None
    endpoint: Optional[str] = None
    adapter_id: str = "generic"
    protocol: Optional[str] = None
    capability_profile_id: str = "default"
    authentication_policy: Optional[str] = None
    enabled: bool = True
    priority: int = 10
    fallback_policy: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    health_status: str = "UNKNOWN"
    version: Optional[str] = None

    def shares_capability_profile(self, other: "Provider") -> bool:
        return self.capability_profile_id == other.capability_profile_id

    def is_valid_fallback_for(self, other: "Provider", *, role: Optional[str] = None) -> bool:
        if not self.shares_capability_profile(other):
            return False
        if role is None:
            return True
        return role in self.roles and role in other.roles

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "Provider":
        connection_kind = config.get("connection_kind", "API")
        capability_profile_id = (
            config.get("capability_profile_id")
            or config.get("provider_capability_profile_id")
            or config.get("profile_id")
            or "default"
        )
        return cls(
            id=config["id"],
            name=config.get("name", config["id"]),
            description=config.get("description"),
            roles=config.get("roles", []),
            connection_kind=ConnectionKind(connection_kind),
            transport=config.get("transport"),
            endpoint=config.get("endpoint"),
            adapter_id=config.get("adapter_id", "generic"),
            protocol=config.get("protocol"),
            capability_profile_id=capability_profile_id,
            authentication_policy=config.get("authentication_policy"),
            enabled=config.get("enabled", True),
            priority=config.get("priority", 10),
            fallback_policy=config.get("fallback_policy", {}),
            metadata=config.get("metadata", {}),
            health_status=config.get("health_status", "UNKNOWN"),
            version=config.get("version"),
        )

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

class SyncDirection(str, Enum):
    PUSH = "PUSH"
    PULL = "PULL"
    CONFLICT = "CONFLICT"

class SyncConfig(BaseModel):
    provider_type: str
    endpoint_url: Optional[str] = None
    bucket_name: Optional[str] = None
    path: Optional[str] = None
    encryption_key_hash: str

class SyncStatus(BaseModel):
    last_synced_at: Optional[datetime] = None
    sync_direction: SyncDirection
    remote_version: Optional[str] = None
    local_version: Optional[str] = None

class IdempotencyRecord(BaseModel):
    idempotency_key: str
    workflow_id: str
    step_id: str
    provider_id: str
    status: str
    created_at: datetime
    confirmed_at: Optional[datetime] = None
