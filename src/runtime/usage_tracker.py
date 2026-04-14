from __future__ import annotations

from pydantic import BaseModel, Field

from config.settings import ModelPricing


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def add(self, other: "Usage | None") -> "Usage":
        if other is None:
            return self
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_tokens += other.cached_tokens
        return self


class TurnUsageSnapshot(BaseModel):
    turn_id: str
    usage: Usage
    estimated_cost: float


class UsageTracker:
    def __init__(self, pricing: ModelPricing) -> None:
        self.pricing = pricing
        self.total = Usage()
        self.turns: list[TurnUsageSnapshot] = []

    def accumulate(self, usage: Usage | None) -> Usage:
        self.total.add(usage)
        return self.get_total_usage()

    def record_turn(self, turn_id: str, usage: Usage | None) -> TurnUsageSnapshot:
        effective_usage = usage.model_copy() if usage is not None else Usage()
        snapshot = TurnUsageSnapshot(
            turn_id=turn_id,
            usage=effective_usage,
            estimated_cost=self.estimate_cost(effective_usage),
        )
        self.turns.append(snapshot)
        self.accumulate(effective_usage)
        return snapshot

    def get_total_usage(self) -> Usage:
        return self.total.model_copy()

    def get_turn_history(self) -> list[TurnUsageSnapshot]:
        return [snapshot.model_copy() for snapshot in self.turns]

    def estimate_cost(self, usage: Usage | None = None) -> float:
        target = usage or self.total
        return (
            target.input_tokens / 1_000_000 * self.pricing.input_per_million
            + target.output_tokens / 1_000_000 * self.pricing.output_per_million
        )
