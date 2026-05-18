from __future__ import annotations

import asyncio

from ui.prompt_io import PromptIO


class _PromptSession:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def prompt_async(self, *args, **kwargs) -> str:
        self.calls.append((args, kwargs))
        return "value"


def test_secret_prompt_does_not_enable_password_masking() -> None:
    session = _PromptSession()
    prompt_io = PromptIO(session)  # type: ignore[arg-type]

    value = asyncio.run(prompt_io.secret("API Key"))

    assert value == "value"
    assert session.calls[0][1].get("is_password") is None
