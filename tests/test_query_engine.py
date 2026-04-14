from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from app.cli import parse_args
from app.main import build_runtime
from engine.events import ErrorEvent, FinalAnswerEvent
from engine.message_schema import ToolUseBlock
from llm.base import LLMAdapter, LLMAssistantDone, LLMTextDelta, LLMToolUse
from runtime.usage_tracker import Usage


class FakeLLMAdapter(LLMAdapter):
    def __init__(self, responses: list[str], *, emit_tool_use: bool = False) -> None:
        self.responses = responses
        self.emit_tool_use = emit_tool_use

    async def stream_chat(
        self,
        messages,
        system_prompt: str,
        tools,
        temperature: float,
    ) -> AsyncIterator[LLMTextDelta | LLMToolUse | LLMAssistantDone]:
        del messages, system_prompt, tools, temperature
        text = self.responses.pop(0)
        yield LLMTextDelta(delta=text)
        if self.emit_tool_use:
            yield LLMToolUse(
                block=ToolUseBlock(name="web_search", input={"query": "A股"}),
            )
        yield LLMAssistantDone(usage=Usage(input_tokens=10, output_tokens=5))


class RaisingLLMAdapter(LLMAdapter):
    async def stream_chat(
        self,
        messages,
        system_prompt: str,
        tools,
        temperature: float,
    ) -> AsyncIterator[LLMTextDelta | LLMAssistantDone]:
        del messages, system_prompt, tools, temperature
        raise RuntimeError("boom")
        yield  # pragma: no cover


async def _collect_events(engine, prompt: str):
    return [event async for event in engine.submit_user_input(prompt)]


def test_query_engine_accumulates_multi_turn_history_and_resume(tmp_path: Path) -> None:
    runtime = build_runtime(parse_args(["--cwd", str(tmp_path)]))
    runtime.query_engine.llm = FakeLLMAdapter(["first answer", "second answer"])

    first_events = asyncio.run(_collect_events(runtime.query_engine, "first question"))
    second_events = asyncio.run(_collect_events(runtime.query_engine, "second question"))

    assert isinstance(first_events[-1], FinalAnswerEvent)
    assert isinstance(second_events[-1], FinalAnswerEvent)
    assert runtime.query_engine.last_turn is not None
    assert runtime.query_engine.last_turn.turn_index == 2
    assert len(runtime.query_engine.get_messages()) == 4
    assert runtime.query_engine.get_messages()[0].to_plain_text() == "first question"
    assert runtime.query_engine.get_messages()[1].to_plain_text() == "first answer"
    assert runtime.query_engine.get_messages()[2].to_plain_text() == "second question"
    assert runtime.query_engine.get_messages()[3].to_plain_text() == "second answer"

    resumed = build_runtime(
        parse_args(
            [
                "--cwd",
                str(tmp_path),
                "--resume",
                runtime.query_engine.session.session_id,
            ]
        )
    )
    assert resumed.query_engine.turn_counter == 2
    assert len(resumed.query_engine.get_messages()) == 4


def test_query_engine_blocks_when_budget_would_be_exceeded(tmp_path: Path) -> None:
    runtime = build_runtime(parse_args(["--cwd", str(tmp_path)]))
    runtime.query_engine.llm = FakeLLMAdapter(["should not run"])
    runtime.query_engine.token_budget.settings.max_context_tokens = 32
    runtime.query_engine.token_budget.settings.max_output_tokens = 8

    events = asyncio.run(
        _collect_events(
            runtime.query_engine,
            "x" * 400,
        )
    )

    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "token_budget_exceeded"
    stored_messages = runtime.session_store.load_messages(runtime.query_engine.session.session_id)
    assert len(stored_messages) == 1
    assert stored_messages[0].to_plain_text() == "x" * 400


def test_query_engine_persists_user_message_before_model_failure(tmp_path: Path) -> None:
    runtime = build_runtime(parse_args(["--cwd", str(tmp_path)]))
    runtime.query_engine.llm = RaisingLLMAdapter()

    events = asyncio.run(_collect_events(runtime.query_engine, "hello"))

    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "RuntimeError"
    stored_messages = runtime.session_store.load_messages(runtime.query_engine.session.session_id)
    assert len(stored_messages) == 1
    assert stored_messages[0].to_plain_text() == "hello"
