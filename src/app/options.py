from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CLIOptions:
    prompt: str | None
    model: str | None
    system_prompt: str | None
    resume: str | bool | None
    debug: bool
    print_thinking: bool
    cwd: Path | None
    non_interactive: bool
