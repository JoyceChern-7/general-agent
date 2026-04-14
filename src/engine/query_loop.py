from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from engine.events import AssistantDeltaEvent, AssistantDoneEvent, QueryEvent, ToolUseEvent
from engine.message_schema import ContentBlock, TextBlock, ToolUseBlock, assistant_message_from_blocks
from engine.turn_state import QueryTurnState
from llm.base import LLMAdapter, LLMAssistantDone, LLMTextDelta, LLMToolUse


class QueryLoop(Protocol):
    async def run(
        self,
        turn: QueryTurnState,
        *,
        llm: LLMAdapter,
        system_prompt: str,
        tools: list[dict],
        temperature: float,
    ) -> AsyncIterator[QueryEvent]:
        ...


class DefaultQueryLoop:
    async def run(
        self,
        turn: QueryTurnState,
        *,
        llm: LLMAdapter,
        system_prompt: str,
        tools: list[dict],
        temperature: float,
    ) -> AsyncIterator[QueryEvent]:
        turn.stage = "running"

        text_blocks: list[TextBlock] = []
        tool_blocks: list[ToolUseBlock] = []

        async for llm_event in llm.stream_chat(
            messages=turn.messages_for_query,
            system_prompt=system_prompt,
            tools=tools,
            temperature=temperature,
        ):
            if isinstance(llm_event, LLMTextDelta):
                turn.append_stream_delta(llm_event.delta)
                yield AssistantDeltaEvent(
                    session_id=turn.session_id,
                    turn_id=turn.turn_id,
                    delta=llm_event.delta,
                )
                continue

            if isinstance(llm_event, LLMToolUse):
                turn.add_tool_call(llm_event.block)
                tool_blocks.append(llm_event.block)
                yield ToolUseEvent(
                    session_id=turn.session_id,
                    turn_id=turn.turn_id,
                    block=llm_event.block,
                )
                continue

            if isinstance(llm_event, LLMAssistantDone):
                turn.usage_delta = llm_event.usage or turn.usage_delta

        assistant_text = "".join(turn.streamed_text_parts).strip()
        if assistant_text:
            text_blocks.append(TextBlock(text=assistant_text))
        if not text_blocks and not tool_blocks:
            text_blocks.append(TextBlock(text="(empty assistant response)"))

        blocks: list[ContentBlock] = [*text_blocks, *tool_blocks]
        assistant_message = assistant_message_from_blocks(blocks)
        turn.record_generated_message(assistant_message)

        if tool_blocks:
            turn.stop_reason = "tool_use"
        else:
            turn.stop_reason = "end_turn"

        yield AssistantDoneEvent(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            message=assistant_message,
        )
