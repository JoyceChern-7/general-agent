from __future__ import annotations

from dataclasses import dataclass

from engine.message_schema import Message


@dataclass(slots=True)
class CompactionResult:
    messages: list[Message]
    compacted: bool = False
    reason: str | None = None


class CompactionManager:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def maybe_compact(self, messages: list[Message]) -> CompactionResult:
        # Interface-first placeholder. The startup path calls this for real, so
        # later micro/session/API compaction can replace the implementation
        # without touching app.main or QueryEngine.
        return CompactionResult(messages=messages, compacted=False)

    def mark_boundary(self, messages: list[Message], reason: str) -> list[Message]:
        del reason
        return messages

    def recover_from_overflow(self, messages: list[Message]) -> CompactionResult:
        return CompactionResult(messages=messages, compacted=False, reason="overflow_noop")
