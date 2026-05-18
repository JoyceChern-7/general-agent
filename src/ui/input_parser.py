from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ParsedInput(BaseModel):
    kind: Literal["message", "command", "empty"]
    text: str = ""
    command: str | None = None
    args: list[str] = []


def parse_input(raw: str) -> ParsedInput:
    text = raw.strip()
    if not text:
        return ParsedInput(kind="empty")
    if text.startswith("/"):
        parts = text[1:].split()
        if not parts:
            return ParsedInput(kind="empty")
        command, *args = parts
        return ParsedInput(kind="command", text=text, command=command, args=args)
    return ParsedInput(kind="message", text=text)
