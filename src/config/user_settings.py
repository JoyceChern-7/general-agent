from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from config.paths import get_user_settings_path


DEFAULT_MODEL_TIERS: dict[str, str] = {
    "swift": "deepseek-chat",
    "balanced": "deepseek-v4-pro",
    "depth": "deepseek-reasoner",
}


MODEL_TIER_LABELS: dict[str, str] = {
    "swift": "Swift",
    "balanced": "Balanced",
    "depth": "Depth",
}


class UserModelTier(BaseModel):
    label: str
    model: str


class UserSettings(BaseModel):
    provider: str = "openai-compatible"
    api_key: str | None = None
    base_url: str | None = None
    default_tier: str = "balanced"
    models: dict[str, UserModelTier] = Field(default_factory=dict)


def default_user_settings() -> UserSettings:
    return UserSettings(
        models={
            name: UserModelTier(label=MODEL_TIER_LABELS[name], model=model)
            for name, model in DEFAULT_MODEL_TIERS.items()
        }
    )


def load_user_settings(path: Path | None = None) -> UserSettings:
    settings_path = path or get_user_settings_path()
    if not settings_path.exists():
        return UserSettings()

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        return UserSettings.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Invalid user settings file: {settings_path}") from exc


def save_user_settings(settings: UserSettings, path: Path | None = None) -> Path:
    settings_path = path or get_user_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.model_dump(mode="json", exclude_none=True)
    settings_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return settings_path


def resolve_model_from_tier(settings: UserSettings, tier: str | None) -> str | None:
    if not tier:
        return None
    model_tier = settings.models.get(tier)
    if model_tier:
        return model_tier.model
    return DEFAULT_MODEL_TIERS.get(tier)
