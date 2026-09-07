from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ProtocolType(str, Enum):
    MCP = "MCP"
    ACP = "ACP"
    A2A = "A2A"


class MCPConfig(BaseModel):
    server_url: str
    transport: str = "streamable-http"
    capabilities: List[str] = Field(default_factory=list)
    auth_token: Optional[str] = None
    default_tool: Optional[str] = Field(default=None, min_length=1, max_length=256)
    default_arguments: Dict[str, Any] = Field(default_factory=dict)


class ACPConfig(BaseModel):
    agent_path: str
    session_id: Optional[str] = None
    resume_supported: bool = False


class A2AConfig(BaseModel):
    agent_card_url: str
    capabilities: List[str] = Field(default_factory=list)
    auth_method: Optional[str] = None


class ProtocolConnection(BaseModel):
    protocol_type: ProtocolType
    config: Union[MCPConfig, ACPConfig, A2AConfig]
    state: str = "DISCONNECTED"
    health: str = "UNKNOWN"
