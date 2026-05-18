from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_session_dir(tmp_path, monkeypatch) -> None:
    home = tmp_path / "user-home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(
        "SIYI_SESSION_DIR",
        str(home / ".siyi" / "sessions"),
    )
