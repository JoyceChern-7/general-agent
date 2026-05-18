from __future__ import annotations

import os
from pathlib import Path


def get_siyi_config_home() -> Path:
    raw_path = os.environ.get("SIYI_CONFIG_DIR")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return (Path.home() / ".SiYi").resolve()


def get_session_dir() -> Path:
    raw_path = os.environ.get("SIYI_SESSION_DIR")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return (Path.home() / ".siyi" / "sessions").resolve()


def get_user_settings_path() -> Path:
    return get_siyi_config_home() / "settings.json"
