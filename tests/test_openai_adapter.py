from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pydantic import SecretStr

from engine.message_schema import ThinkingBlock, ToolUseBlock, assistant_message_from_blocks, user_message
from llm.base import LLMAssistantDone, LLMTextDelta, LLMThinkingDelta, LLMToolUse
import llm.openai_adapter as openai_adapter_module
from llm.openai_adapter import OpenAIChatAdapter


class _FakeStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        if not hasattr(self, "_step"):
            self._step = 0

        if self._step == 0:
            self._step += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5),
            )

        if self._step == 1:
            self._step += 1
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="toolu_123",
                                    function=SimpleNamespace(
                                        name="web_search",
                                        arguments='{"query":"latest developer docs"}',
                                    ),
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5),
            )

        raise StopAsyncIteration


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeStream()


class _FakeAsyncOpenAI:
    completions = _FakeCompletions()

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=self.completions)


def test_openai_adapter_streams_text_tool_calls_and_usage(monkeypatch) -> None:
    monkeypatch.setattr(openai_adapter_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    adapter = OpenAIChatAdapter(
        model="test-model",
        api_key=SecretStr("test-key"),
        base_url="https://example.test",
        timeout_seconds=600.0,
    )

    async def collect_events():
        return [
            event
            async for event in adapter.stream_chat(
                messages=[user_message("hello")],
                system_prompt="system",
                tools=[],
                temperature=0.2,
            )
        ]

    events = asyncio.run(collect_events())

    assert isinstance(events[0], LLMTextDelta)
    assert events[0].delta == "hello"

    assert isinstance(events[1], LLMToolUse)
    assert events[1].block.name == "web_search"
    assert events[1].block.input == {"query": "latest developer docs"}

    assert isinstance(events[2], LLMAssistantDone)
    assert events[2].usage is not None
    assert events[2].usage.input_tokens == 3
    assert events[2].usage.output_tokens == 5

    kwargs = _FakeAsyncOpenAI.completions.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}


def test_openai_adapter_extracts_openai_compatible_usage_shapes() -> None:
    openai_usage = openai_adapter_module._extract_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=3,
                completion_tokens=5,
                prompt_tokens_details=SimpleNamespace(cached_tokens=2),
            )
        )
    )
    input_output_usage = openai_adapter_module._extract_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=7,
                output_tokens=11,
                cache_read_input_tokens=13,
            )
        )
    )

    assert openai_usage is not None
    assert openai_usage.input_tokens == 3
    assert openai_usage.output_tokens == 5
    assert openai_usage.cached_tokens == 2
    assert input_output_usage is not None
    assert input_output_usage.input_tokens == 20
    assert input_output_usage.output_tokens == 11
    assert input_output_usage.cached_tokens == 13


class _FakeReasoningStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        if not hasattr(self, "_step"):
            self._step = 0

        if self._step == 0:
            self._step += 1
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None, reasoning_content="think")
                    )
                ],
                usage=None,
            )

        raise StopAsyncIteration


class _FakeReasoningCompletions:
    async def create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeReasoningStream()


class _FakeReasoningAsyncOpenAI:
    completions = _FakeReasoningCompletions()

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.chat = SimpleNamespace(completions=self.completions)


def test_openai_adapter_preserves_reasoning_content(monkeypatch) -> None:
    monkeypatch.setattr(openai_adapter_module, "AsyncOpenAI", _FakeReasoningAsyncOpenAI)
    adapter = OpenAIChatAdapter(
        model="test-model",
        api_key=SecretStr("test-key"),
        base_url=None,
        timeout_seconds=600.0,
    )

    async def collect_events():
        return [
            event
            async for event in adapter.stream_chat(
                messages=[user_message("hello")],
                system_prompt="system",
                tools=[],
                temperature=0.2,
            )
        ]

    events = asyncio.run(collect_events())

    assert isinstance(events[0], LLMThinkingDelta)
    assert events[0].delta == "think"

    messages = openai_adapter_module._to_openai_messages(
        "system",
        [
            assistant_message_from_blocks(
                [
                    ThinkingBlock(text="think"),
                    ToolUseBlock(id="toolu_1", name="ToolSearch", input={"query": "file"}),
                ]
            )
        ],
    )
    assert messages[1]["reasoning_content"] == "think"
