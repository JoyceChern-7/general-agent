from __future__ import annotations

from pathlib import Path

from app.cli import parse_args
from config.settings import load_settings
from config.user_settings import UserModelTier, UserSettings, save_user_settings
from runtime.token_budget import AUTO_COMPACT_THRESHOLD_TOKENS, TokenBudget


def test_load_settings_reads_user_level_api_config(tmp_path: Path, monkeypatch) -> None:
    config_home = tmp_path / "home-config"
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(config_home))
    monkeypatch.delenv("SIYI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    save_user_settings(
        UserSettings(
            provider="openai-compatible",
            api_key="user-key",
            base_url="https://api.example.test/v1",
            default_tier="balanced",
            models={
                "balanced": UserModelTier(label="Balanced", model="user-balanced"),
            },
        )
    )

    settings = load_settings(parse_args([]), cwd)

    assert settings.model.api_key is not None
    assert settings.model.provider == "openai-compatible"
    assert settings.model.api_key.get_secret_value() == "user-key"
    assert settings.model.base_url == "https://api.example.test/v1"
    assert settings.model.model == "user-balanced"


def test_load_settings_precedence_cli_then_env_then_user(tmp_path: Path, monkeypatch) -> None:
    config_home = tmp_path / "home-config"
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(config_home))
    monkeypatch.setenv("SIYI_API_KEY", "env-key")
    monkeypatch.setenv("SIYI_MODEL", "env-model")
    save_user_settings(
        UserSettings(
            api_key="user-key",
            default_tier="balanced",
            models={
                "balanced": UserModelTier(label="Balanced", model="user-balanced"),
            },
        )
    )

    settings = load_settings(
        parse_args(["--api-key", "cli-key", "--model", "cli-model"]),
        cwd,
    )

    assert settings.model.api_key is not None
    assert settings.model.api_key.get_secret_value() == "cli-key"
    assert settings.model.model == "cli-model"


def test_load_settings_model_tier_uses_builtin_defaults(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(tmp_path / "empty-config"))

    settings = load_settings(parse_args(["--model-tier", "swift"]), cwd)

    assert settings.model.model == "deepseek-chat"


def test_load_settings_can_disable_compaction(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(tmp_path / "empty-config"))
    monkeypatch.setenv("SIYI_DISABLE_COMPACT", "true")

    settings = load_settings(parse_args([]), cwd)

    assert settings.runtime.compaction_enabled is False
    assert settings.runtime.auto_compact_enabled is False


def test_token_budget_uses_fixed_auto_compaction_threshold(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(tmp_path / "empty-config"))
    settings = load_settings(parse_args([]), cwd)
    settings.runtime.max_context_tokens = 200_000
    settings.runtime.max_output_tokens = 20_000

    snapshot = TokenBudget(settings.runtime).evaluate(
        messages=[],
        system_prompt="",
        tools=[],
    )

    assert snapshot.autocompact_threshold == AUTO_COMPACT_THRESHOLD_TOKENS
    assert snapshot.should_autocompact is False
    assert "warning_threshold" not in snapshot.model_dump()
    assert "blocking_limit" not in snapshot.model_dump()
    assert "max_context_tokens" not in snapshot.model_dump()
    assert "max_output_tokens" not in snapshot.model_dump()
