from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CLIOptions:
    prompt: str | None
    internal_worker: bool
    model: str | None
    model_tier: str | None
    api_key: str | None
    base_url: str | None
    system_prompt: str | None
    resume: str | bool | None
    debug: bool
    print_thinking: bool
    cwd: Path | None
    non_interactive: bool
