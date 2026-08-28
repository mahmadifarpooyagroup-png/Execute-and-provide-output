"""Core models for Atrin AI Control Plane."""

from enum import Enum
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field


class ConnectionKind(str, Enum):
    """Connection kind for providers."""
    WEB = "web"
    DESKTOP = "desktop"
    API = "api"
    CLI = "cli"
    MCP = "mcp"
    A2A = "a2a"
    ACP = "acp"
    LOCAL = "local"


class AuthState(str, Enum):
    """Authentication state machine states per Section 13.1."""
    UNKNOWN = "UNKNOWN"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    AUTHENTICATING = "AUTHENTICATING"
    AUTHENTICATED = "AUTHENTICATED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    AUTH_REJECTED = "AUTH_REJECTED"
    AUTH_ERROR = "AUTH_ERROR"


class Provider(BaseModel):
    """Provider definition per Section 8."""
    id: str
    name: str
    description: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    connection_kind: ConnectionKind
    transport: Optional[str] = None
    endpoint: Optional[str] = None
    adapter_id: Optional[str] = None
    protocols: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    auth_policy: Optional[str] = None
    enabled: bool = True
    priority: int = 0
    fallback_policy: Optional[str] = None
    trust_level: Optional[str] = None
    permissions_policy: Optional[str] = None
    version: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    health_status: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None


class ProviderProfile(BaseModel):
    """Provider Profile / Account model per Section 8 and 20.
    
    Includes fencing_token for session lease/lock per Section 20.1.
    """
    id: str
    provider_id: str
    account_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    browser_profile_path: Optional[str] = None
    app_profile_path: Optional[str] = None
    fencing_token: int = 0
    trust_level: Optional[str] = None
    enabled: bool = True
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None


class Session(BaseModel):
    """Session model per Section 20."""
    session_id: str
    provider_profile_id: str
    account_id: Optional[str] = None
    transport: Optional[str] = None
    state: AuthState = AuthState.UNKNOWN
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    lock_owner: Optional[str] = None
    health: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class IdempotencyRecord(BaseModel):
    """Idempotency ledger record per Section 35.1."""
    idempotency_key: str
    workflow_id: str
    step_id: str
    provider_id: str
    status: str  # PENDING | CONFIRMED | FAILED
    external_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_at: Optional[datetime] = None
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        populate_by_name = True
