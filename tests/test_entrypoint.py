from __future__ import annotations

from pathlib import Path

from app.cli import parse_args
from app.main import build_runtime, run


def test_parse_args_entry_layer_flags(tmp_path: Path) -> None:
    options = parse_args(
        [
            "--model",
            "gpt-test",
            "--system-prompt",
            "test prompt",
            "--resume",
            "session-1",
            "--debug",
            "--print-thinking",
            "--cwd",
            str(tmp_path),
            "--non-interactive",
            "hello",
        ]
    )

    assert options.model == "gpt-test"
    assert options.system_prompt == "test prompt"
    assert options.resume == "session-1"
    assert options.debug is True
    assert options.print_thinking is True
    assert options.cwd == tmp_path.resolve()
    assert options.non_interactive is True
    assert options.prompt == "hello"


def test_build_runtime_wires_core_services(tmp_path: Path) -> None:
    options = parse_args(["--cwd", str(tmp_path), "--non-interactive", "hello"])
    runtime = build_runtime(options)

    assert runtime.settings.runtime.cwd == tmp_path.resolve()
    assert runtime.settings.runtime.session_dir == (tmp_path.resolve() / ".general-agent" / "sessions")
    assert runtime.settings.runtime.initial_prompt == "hello"
    assert runtime.settings.runtime.non_interactive is True
    assert runtime.query_engine.session.session_id.startswith("sess_")
    assert runtime.session_store.root.exists()


def test_non_interactive_without_prompt_fails_before_runtime(tmp_path: Path) -> None:
    options = parse_args(["--cwd", str(tmp_path), "--non-interactive"])

    import asyncio

    exit_code = asyncio.run(run(options))

    assert exit_code == 2
    assert not (tmp_path / ".general-agent").exists()
