from __future__ import annotations

from pydantic import BaseModel

from config.settings import RuntimeSettings
from engine.message_schema import Message


class BudgetSnapshot(BaseModel):
    estimated_tokens: int
    max_context_tokens: int
    max_output_tokens: int
    warning_threshold: int
    autocompact_threshold: int
    blocking_limit: int
    remaining_input_budget: int
    should_warn: bool
    should_autocompact: bool
    is_blocking_limit: bool


class TokenBudget:
    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings

    def estimate_request_tokens(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[dict],
    ) -> int:
        total_chars = len(system_prompt)
        total_chars += sum(len(str(tool)) for tool in tools)
        total_chars += sum(len(message.to_plain_text()) for message in messages)
        return max(1, total_chars // 4)

    def evaluate(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        tools: list[dict],
    ) -> BudgetSnapshot:
        estimated_tokens = self.estimate_request_tokens(messages, system_prompt, tools)
        warning_threshold = int(self.settings.max_context_tokens * 0.8)
        autocompact_threshold = int(self.settings.max_context_tokens * 0.9)
        blocking_limit = self.settings.max_context_tokens - self.settings.max_output_tokens
        remaining_input_budget = max(0, blocking_limit - estimated_tokens)

        return BudgetSnapshot(
            estimated_tokens=estimated_tokens,
            max_context_tokens=self.settings.max_context_tokens,
            max_output_tokens=self.settings.max_output_tokens,
            warning_threshold=warning_threshold,
            autocompact_threshold=autocompact_threshold,
            blocking_limit=blocking_limit,
            remaining_input_budget=remaining_input_budget,
            should_warn=estimated_tokens >= warning_threshold,
            should_autocompact=estimated_tokens >= autocompact_threshold,
            is_blocking_limit=estimated_tokens >= blocking_limit,
        )

    def should_warn(self, estimated_tokens: int) -> bool:
        return estimated_tokens >= int(self.settings.max_context_tokens * 0.8)

    def should_autocompact(self, estimated_tokens: int) -> bool:
        return estimated_tokens >= int(self.settings.max_context_tokens * 0.9)

    def is_blocking_limit(self, estimated_tokens: int) -> bool:
        return estimated_tokens >= self.settings.max_context_tokens - self.settings.max_output_tokens
