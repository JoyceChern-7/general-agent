from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import SecretStr
from openai import AsyncOpenAI
from config.settings import ModelSettings
from engine.message_schema import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    normalize_messages_for_api,
)
from llm.base import LLMAdapter, LLMAssistantDone, LLMEvent, LLMTextDelta, LLMThinkingDelta, LLMToolUse
from runtime.usage_tracker import Usage


class ModelConfigurationError(RuntimeError):
    pass


class OpenAIChatAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        api_key: SecretStr | None,
        base_url: str | None,
        timeout_seconds: float,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: ModelSettings) -> "OpenAIChatAdapter":
        return cls(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
        )

    async def stream_chat(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[dict],
        temperature: float,
    ) -> AsyncIterator[LLMEvent]:
        if self.api_key is None:
            raise ModelConfigurationError(
                "API key is not configured. Run /login or set SIYI_API_KEY/OPENAI_API_KEY."
            )

        client = AsyncOpenAI(
            api_key=self.api_key.get_secret_value(),
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        )
        kwargs = {
            "model": self.model,
            "messages": _to_openai_messages(system_prompt, messages),
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        create_result = client.chat.completions.create(**kwargs)
        stream = await create_result if inspect.isawaitable(create_result) else create_result
        usage = Usage()
        tool_call_accumulator: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            delta = _extract_delta(choice)
            if delta:
                yield LLMTextDelta(delta=delta)

            reasoning_delta = _extract_reasoning_delta(choice)
            if reasoning_delta:
                yield LLMThinkingDelta(delta=reasoning_delta)

            _accumulate_tool_calls(choice, tool_call_accumulator)
            usage = _extract_usage(chunk) or usage

        for index in sorted(tool_call_accumulator):
            raw = tool_call_accumulator[index]
            yield LLMToolUse(
                block=ToolUseBlock(
                    id=raw["id"],
                    name=raw["name"],
                    input=_parse_tool_arguments(raw["arguments"]),
                )
            )

        yield LLMAssistantDone(usage=usage)


def _to_openai_messages(system_prompt: str, messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in normalize_messages_for_api(messages):
        if message.is_virtual:
            continue

        if message.role == "assistant":
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, ThinkingBlock):
                    thinking_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.input, ensure_ascii=False),
                            },
                        }
                    )
            payload: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or ""}
            if thinking_parts:
                payload["reasoning_content"] = "\n".join(thinking_parts)
            if tool_calls:
                payload["tool_calls"] = tool_calls
            if text_parts or thinking_parts or tool_calls:
                result.append(payload)
            continue

        text_parts = [block.text for block in message.content if isinstance(block, TextBlock)]
        if text_parts:
            result.append({"role": message.role, "content": "\n".join(text_parts)})
            continue

        tool_results = [
            block
            for block in message.content
            if isinstance(block, ToolResultBlock)
        ]
        for block in tool_results:
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": block.tool_use_id,
                    "content": block.content,
                }
            )
    return result


def _extract_delta(choice: Any) -> str | None:
    if not choice or not getattr(choice, "delta", None):
        return None

    content = getattr(choice.delta, "content", None)
    return _coerce_content_to_text(content)


def _extract_reasoning_delta(choice: Any) -> str | None:
    if not choice or not getattr(choice, "delta", None):
        return None

    content = getattr(choice.delta, "reasoning_content", None)
    if content is None:
        content = getattr(choice.delta, "reasoning", None)
    return _coerce_content_to_text(content)


def _coerce_content_to_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts) or None
    return str(content)


def _accumulate_tool_calls(choice: Any, accumulator: dict[int, dict[str, Any]]) -> None:
    if not choice or not getattr(choice, "delta", None):
        return

    tool_calls = getattr(choice.delta, "tool_calls", None)
    if not tool_calls:
        return

    for item in tool_calls:
        index = int(getattr(item, "index", 0) or 0)
        current = accumulator.setdefault(
            index,
            {
                "id": getattr(item, "id", None),
                "name": getattr(getattr(item, "function", None), "name", None),
                "arguments": "",
            },
        )
        item_id = getattr(item, "id", None)
        if item_id:
            current["id"] = item_id
        function = getattr(item, "function", None)
        if function is not None:
            function_name = getattr(function, "name", None)
            if function_name:
                current["name"] = function_name
            arguments = getattr(function, "arguments", None)
            if arguments:
                current["arguments"] += arguments


def _parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {"__raw_arguments": raw_arguments}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _extract_usage(chunk: Any) -> Usage | None:
    raw_usage = getattr(chunk, "usage", None)
    if raw_usage is None:
        return None

    prompt_tokens = _usage_int(raw_usage, "prompt_tokens")
    input_tokens = prompt_tokens
    if input_tokens is None:
        input_tokens = _usage_int(raw_usage, "input_tokens") or 0
        input_tokens += _usage_int(raw_usage, "cache_creation_input_tokens") or 0
        input_tokens += _usage_int(raw_usage, "cache_read_input_tokens") or 0

    cached_tokens = _usage_int(raw_usage, "cached_tokens") or 0
    prompt_details = getattr(raw_usage, "prompt_tokens_details", None)
    input_details = getattr(raw_usage, "input_tokens_details", None)
    cached_tokens = max(
        cached_tokens,
        _usage_int(prompt_details, "cached_tokens") or 0,
        _usage_int(input_details, "cached_tokens") or 0,
        _usage_int(raw_usage, "cache_read_input_tokens") or 0,
    )

    completion_tokens = _usage_int(raw_usage, "completion_tokens")
    output_tokens = (
        completion_tokens
        if completion_tokens is not None
        else _usage_int(raw_usage, "output_tokens") or 0
    )

    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )


def _usage_int(raw_usage: Any, name: str) -> int | None:
    if raw_usage is None:
        return None
    if isinstance(raw_usage, dict):
        value = raw_usage.get(name)
    else:
        value = getattr(raw_usage, name, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
