from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "You are General Agent, named 将军. You are a careful general-purpose agent. "
    "Use tools when fresh data, files, or calculations are required. State "
    "uncertainty clearly and avoid pretending to have verified information "
    "when you have not."
)


class ModelPricing(BaseModel):
    input_per_million: float = 0.0
    output_per_million: float = 0.0


class ModelSettings(BaseModel):
    provider: Literal["openai"] = "openai"
    model: str = "gpt-4o-mini"
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=600.0, gt=0)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    print_thinking: bool = False
    temperature: float = Field(default=1, ge=0.0, le=2.0)
    pricing: ModelPricing = Field(default_factory=ModelPricing)


class ToolSettings(BaseModel):
    web_search_enabled: bool = True
    read_file_enabled: bool = True
    shell_enabled: bool = False
    tushare_enabled: bool = True
    shell_requires_approval: bool = True
    max_tool_result_chars: int = Field(default=20_000, ge=1_000)


class RuntimeSettings(BaseModel):
    cwd: Path
    debug: bool = False
    non_interactive: bool = False
    initial_prompt: str | None = None
    resume: str | bool | None = None
    session_dir: Path
    max_turns: int = Field(default=64, ge=1, le=64)
    max_context_tokens: int = Field(default=1_000_000)
    max_output_tokens: int = Field(default=1_000_000)
    compaction_enabled: bool = False

    @field_validator("cwd", "session_dir")
    @classmethod
    def expand_paths(cls, value: Path) -> Path:
        return value.expanduser().resolve() # Resolve to handle cases where the path is a symlink or contains "..", e.g "~/sessions" -> "/home/user/sessions"


class AppSettings(BaseModel):
    model: ModelSettings
    tools: ToolSettings
    runtime: RuntimeSettings


class EnvSettings(BaseSettings):
    tushare_token: SecretStr | None = None
    debug: bool = False
    max_turns: int = 8
    max_context_tokens: int = 200_000
    max_output_tokens: int = 8_000

    model_config = SettingsConfigDict(env_prefix="GENERAL_AGENT_", extra="ignore")


class JsonRuntimeSettings(BaseModel):
    api_timeout_ms: int | None = None
    debug: bool | None = None
    max_turns: int | None = None
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None
    session_dir: Path | None = None
    compaction_enabled: bool | None = None


class JsonSettings(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    runtime: JsonRuntimeSettings = Field(default_factory=JsonRuntimeSettings)

# Returns the first non-None value from the provided arguments, or None if all are None.
# e.g. _first_value(None, "hello", None) -> "hello"
def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _load_json_settings(cwd: Path) -> JsonSettings:
    path = cwd / ".general-agent" / "settings.json"
    if not path.exists():
        return JsonSettings()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return JsonSettings.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Invalid settings file: {path}") from exc


def _json_env(settings: JsonSettings, *names: str) -> str | None:
    for name in names:
        value = settings.env.get(name)
        if value:
            return value
    return None


def load_settings(options, cwd: Path) -> AppSettings:
    json_settings = _load_json_settings(cwd)
    env = EnvSettings()
    default_model_settings = ModelSettings()
    session_dir = cwd / ".general-agent" / "sessions"

    api_key = SecretStr(json_settings.api_key) if json_settings.api_key else default_model_settings.api_key

    base_url = _first_value(
        json_settings.base_url,
        default_model_settings.base_url,
    )
    api_timeout_ms = _first_value(
        _json_env(json_settings, "API_TIMEOUT_MS"),
        json_settings.runtime.api_timeout_ms,
        600_000,
    )

    runtime = RuntimeSettings(
        cwd=cwd,
        debug=bool(options.debug or env.debug or json_settings.runtime.debug),
        non_interactive=bool(options.non_interactive or options.prompt),
        initial_prompt=options.prompt,
        resume=options.resume,
        session_dir=session_dir,
        max_turns=_first_value(json_settings.runtime.max_turns, env.max_turns),
        max_context_tokens=_first_value(json_settings.runtime.max_context_tokens, env.max_context_tokens),
        max_output_tokens=_first_value(json_settings.runtime.max_output_tokens, env.max_output_tokens),
        compaction_enabled=bool(json_settings.runtime.compaction_enabled),
    )
    model = ModelSettings(
        model=options.model or json_settings.model or default_model_settings.model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=float(api_timeout_ms) / 1000.0,
        system_prompt=options.system_prompt or json_settings.system_prompt or DEFAULT_SYSTEM_PROMPT,
        print_thinking=options.print_thinking,
    )
    tushare_token = _first_value(
        env.tushare_token.get_secret_value() if env.tushare_token else None,
        _json_env(json_settings, "TUSHARE_TOKEN"),
    )
    tools = ToolSettings(tushare_enabled=tushare_token is not None)
    return AppSettings(model=model, tools=tools, runtime=runtime)
