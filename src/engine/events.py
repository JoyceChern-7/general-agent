from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.message_schema import Message, ToolResultBlock, ToolUseBlock
from runtime.ids import new_id
from runtime.usage_tracker import Usage


class QueryEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    type: str
    session_id: str | None = None
    turn_id: str | None = None


class AssistantDeltaEvent(QueryEvent):
    type: Literal["assistant_delta"] = "assistant_delta"
    delta: str


class AssistantDoneEvent(QueryEvent):
    type: Literal["assistant_done"] = "assistant_done"
    message: Message


class ToolUseEvent(QueryEvent):
    type: Literal["tool_use"] = "tool_use"
    block: ToolUseBlock


class ToolResultEvent(QueryEvent):
    type: Literal["tool_result"] = "tool_result"
    block: ToolResultBlock


class StatusEvent(QueryEvent):
    type: Literal["status"] = "status"
    message: str
    code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class FinalAnswerEvent(QueryEvent):
    type: Literal["final_answer"] = "final_answer"
    message: Message
    usage: Usage | None = None
    estimated_cost: float | None = None


class ErrorEvent(QueryEvent):
    type: Literal["error"] = "error"
    message: str
    retryable: bool = False
    code: str | None = None
