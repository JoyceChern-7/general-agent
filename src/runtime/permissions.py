from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from config.settings import ToolSettings

PermissionDecision = Literal["allow", "ask", "deny"]


class PermissionResult(BaseModel):
    decision: PermissionDecision
    reason: str | None = None


class PermissionManager:
    def __init__(self, settings: ToolSettings) -> None:
        self.settings = settings

    @classmethod
    def from_settings(cls, settings: ToolSettings) -> "PermissionManager":
        return cls(settings)

    def check(self, tool_name: str, tool_input: dict, context: dict | None = None) -> PermissionResult:
        del tool_input, context
        if tool_name == "shell" and not self.settings.shell_enabled:
            return PermissionResult(decision="deny", reason="shell tool is disabled")
        if tool_name == "shell" and self.settings.shell_requires_approval:
            return PermissionResult(decision="ask", reason="shell tool requires approval")
        return PermissionResult(decision="allow")
