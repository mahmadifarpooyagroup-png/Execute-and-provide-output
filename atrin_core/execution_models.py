from enum import Enum, IntEnum
from typing import List, Optional

from pydantic import BaseModel, Field


class ExecutionTarget(str, Enum):
    POWERSHELL = "POWERSHELL"
    CMD = "CMD"
    BASH = "BASH"
    WSL = "WSL"
    PYTHON = "PYTHON"
    GIT = "GIT"
    FILESYSTEM = "FILESYSTEM"
    PROCESS = "PROCESS"


class PermissionLevel(IntEnum):
    READ_ONLY = 0
    EXECUTE_SAFE = 1
    WRITE = 2
    GIT_COMMIT = 3
    GIT_PUSH = 4


class ExecutionAction(BaseModel):
    action_id: str = Field(min_length=1, max_length=256)
    permission_required: PermissionLevel
    execution_target: ExecutionTarget
    arguments: List[str] = Field(default_factory=list, max_length=256)
    timeout_seconds: int = Field(default=30, ge=1, le=3600)
    max_output_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    working_dir: Optional[str] = Field(default=None, max_length=4096)


class ExecutionResult(BaseModel):
    action_id: str
    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    evidence: str = ""
    error_message: Optional[str] = None
