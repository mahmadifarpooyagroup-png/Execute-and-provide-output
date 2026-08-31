from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DesktopAppType(str, Enum):
    NATIVE = "NATIVE"
    ELECTRON = "ELECTRON"
    WEB_WRAPPER = "WEB_WRAPPER"
    CLI_WRAPPED = "CLI_WRAPPED"


class WindowInfo(BaseModel):
    window_id: str
    title: str
    process_name: str
    automation_id: str


class UIElement(BaseModel):
    element_id: str
    name: str
    control_type: str
    value: Optional[str] = None
    children: List[str] = Field(default_factory=list)
