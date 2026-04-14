from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from pydantic import SecretStr

from engine.message_schema import user_message
from llm.base import LLMAssistantDone, LLMTextDelta, LLMToolUse
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
                                        arguments='{"query":"A股"}',
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
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI),
    )
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
                messages=[user_message("你好")],
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
    assert events[1].block.input == {"query": "A股"}

    assert isinstance(events[2], LLMAssistantDone)
    assert events[2].usage is not None
    assert events[2].usage.input_tokens == 3
    assert events[2].usage.output_tokens == 5

    kwargs = _FakeAsyncOpenAI.completions.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert kwargs["stream"] is True
