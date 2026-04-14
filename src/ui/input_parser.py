from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ParsedInput(BaseModel):
    kind: Literal["message", "command", "empty"]
    text: str = ""
    command: str | None = None


def parse_input(raw: str) -> ParsedInput:
    text = raw.strip()
    if not text:
        return ParsedInput(kind="empty")
    if text.startswith("/"):
        command = text.split(maxsplit=1)[0][1:]
        return ParsedInput(kind="command", text=text, command=command)
    return ParsedInput(kind="message", text=text)
