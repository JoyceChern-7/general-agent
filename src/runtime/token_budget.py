from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from config.settings import RuntimeSettings
from engine.message_schema import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

AUTO_COMPACT_THRESHOLD_TOKENS = 272_000


class BudgetSnapshot(BaseModel):
    estimated_tokens: int
    autocompact_threshold: int
    should_autocompact: bool


class TokenBudget:
    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings

    def estimate_request_tokens(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[dict],
    ) -> int:
        return token_count_with_estimation(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
        )

    def evaluate(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        tools: list[dict],
    ) -> BudgetSnapshot:
        estimated_tokens = self.estimate_request_tokens(messages, system_prompt, tools)
        return BudgetSnapshot(
            estimated_tokens=estimated_tokens,
            autocompact_threshold=AUTO_COMPACT_THRESHOLD_TOKENS,
            should_autocompact=(
                self.settings.auto_compact_enabled
                and estimated_tokens >= AUTO_COMPACT_THRESHOLD_TOKENS
            ),
        )

    def should_autocompact(self, estimated_tokens: int) -> bool:
        return (
            self.settings.auto_compact_enabled
            and estimated_tokens >= AUTO_COMPACT_THRESHOLD_TOKENS
        )


def token_count_with_estimation(
    *,
    messages: list[Message],
    system_prompt: str,
    tools: list[dict],
) -> int:
    usage_anchor_index: int | None = None
    usage_anchor_tokens = 0
    for index in range(len(messages) - 1, -1, -1):
        usage_anchor_tokens = _message_usage_tokens(messages[index])
        if usage_anchor_tokens > 0:
            usage_anchor_index = index
            break

    if usage_anchor_index is None:
        return max(1, rough_count_text(system_prompt) + rough_count_tools(tools) + rough_count_messages(messages))

    new_messages = messages[usage_anchor_index + 1 :]
    return max(1, usage_anchor_tokens + rough_count_messages(new_messages))


def rough_count_messages(messages: list[Message]) -> int:
    return sum(rough_count_message(message) for message in messages)


def rough_count_message(message: Message) -> int:
    total = rough_count_text(message.role)
    for block in message.content:
        if isinstance(block, TextBlock | ThinkingBlock):
            total += rough_count_text(block.text)
            continue
        if isinstance(block, ToolUseBlock):
            total += rough_count_text(block.name)
            total += rough_count_json(block.input)
            continue
        if isinstance(block, ToolResultBlock):
            total += rough_count_text(block.tool_use_id)
            total += rough_count_text(block.content)
    return total


def rough_count_tools(tools: list[dict]) -> int:
    return sum(rough_count_json(tool) for tool in tools)


def rough_count_json(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(value)
    return rough_count_text(text)


def rough_count_text(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _message_usage_tokens(message: Message) -> int:
    if message.role != "assistant":
        return 0
    raw_usage = message.metadata.get("usage")
    if not isinstance(raw_usage, dict):
        return 0
    input_tokens = _int_usage_field(raw_usage, "input_tokens", "prompt_tokens")
    output_tokens = _int_usage_field(raw_usage, "output_tokens", "completion_tokens")
    return max(0, input_tokens + output_tokens)


def _int_usage_field(raw_usage: dict[str, Any], *names: str) -> int:
    for name in names:
        value = raw_usage.get(name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0
