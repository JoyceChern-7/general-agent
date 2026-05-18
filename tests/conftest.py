from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_session_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "SIYI_SESSION_DIR",
        str(tmp_path / "user-home" / ".siyi" / "sessions"),
    )
