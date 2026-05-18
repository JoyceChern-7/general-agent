from __future__ import annotations

from engine.message_schema import (
    ThinkingBlock,
    ToolUseBlock,
    assistant_message_from_blocks,
    tool_result_message,
    user_message,
)
from runtime.token_budget import token_count_with_estimation


def test_token_count_uses_latest_assistant_usage_as_anchor() -> None:
    anchor = assistant_message_from_blocks(
        [],
        metadata={"usage": {"input_tokens": 100, "output_tokens": 10, "cached_tokens": 5}},
    )
    later_user = user_message("abcd")

    count = token_count_with_estimation(
        messages=[anchor, later_user],
        system_prompt="system prompt is already covered by the usage anchor",
        tools=[{"name": "Tool", "description": "already covered"}],
    )

    assert count == 112


def test_token_count_falls_back_to_full_rough_estimate_without_usage() -> None:
    messages = [user_message("abcd")]

    count_without_request_overhead = token_count_with_estimation(
        messages=messages,
        system_prompt="",
        tools=[],
    )
    count_with_request_overhead = token_count_with_estimation(
        messages=messages,
        system_prompt="abcd",
        tools=[{"name": "Tool", "description": "abcdefgh"}],
    )

    assert count_with_request_overhead > count_without_request_overhead


def test_token_count_estimates_thinking_tool_use_and_tool_result_blocks() -> None:
    small = token_count_with_estimation(
        messages=[
            assistant_message_from_blocks(
                [
                    ThinkingBlock(text="abcd"),
                    ToolUseBlock(id="toolu_1", name="Tool", input={"query": "a"}),
                ]
            ),
            tool_result_message(tool_use_id="toolu_1", content="a"),
        ],
        system_prompt="",
        tools=[],
    )
    large = token_count_with_estimation(
        messages=[
            assistant_message_from_blocks(
                [
                    ThinkingBlock(text="abcd" * 20),
                    ToolUseBlock(id="toolu_1", name="Tool", input={"query": "a" * 80}),
                ]
            ),
            tool_result_message(tool_use_id="toolu_1", content="a" * 80),
        ],
        system_prompt="",
        tools=[],
    )

    assert large > small


def test_token_count_accepts_prompt_and_completion_usage_names() -> None:
    anchor = assistant_message_from_blocks(
        [],
        metadata={"usage": {"prompt_tokens": 12, "completion_tokens": 8}},
    )

    assert token_count_with_estimation(messages=[anchor], system_prompt="", tools=[]) == 20
