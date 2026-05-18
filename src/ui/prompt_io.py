from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit import PromptSession


@dataclass(slots=True)
class PromptIO:
    session: PromptSession[str]

    async def text(self, label: str, *, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        value = await self.session.prompt_async(f"{label}{suffix}: ")
        value = value.strip()
        return value or (default or "")

    async def secret(self, label: str, *, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        value = await self.session.prompt_async(f"{label}{suffix}: ")
        value = value.strip()
        return value or (default or "")

    async def choice(
        self,
        label: str,
        *,
        choices: tuple[str, ...],
        default: str,
    ) -> str:
        choice_hint = "/".join(choices)
        while True:
            value = await self.text(f"{label} ({choice_hint})", default=default)
            normalized = value.strip().lower()
            if normalized in choices:
                return normalized
