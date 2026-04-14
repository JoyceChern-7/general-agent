from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from engine.message_schema import ToolResultBlock


class ToolContext(BaseModel):
    cwd: str
    trace_id: str


class ToolResult(BaseModel):
    success: bool
    content: str
    data: dict[str, Any] | None = None
    error: str | None = None


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    async def run(self, raw_input: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

    def to_tool_result_block(self, tool_use_id: str, result: ToolResult) -> ToolResultBlock:
        ...
