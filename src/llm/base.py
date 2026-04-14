from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel

from engine.message_schema import Message, ToolUseBlock
from runtime.usage_tracker import Usage


class LLMTextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    delta: str


class LLMToolUse(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    block: ToolUseBlock


class LLMAssistantDone(BaseModel):
    type: Literal["assistant_done"] = "assistant_done"
    usage: Usage | None = None


LLMEvent = LLMTextDelta | LLMToolUse | LLMAssistantDone


class LLMAdapter:
    async def stream_chat(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[dict],
        temperature: float,
    ) -> AsyncIterator[LLMEvent]:
        raise NotImplementedError
