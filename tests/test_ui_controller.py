from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

from config.settings import ModelSettings
from ui.controller import REPLController
from ui.input_parser import parse_input


@dataclass(slots=True)
class _Snapshot:
    session_id: str = "sess_test"
    cwd: str = "C:/workspace"
    model: str = "gpt-test"
    turn_count: int = 1
    message_count: int = 2
    completed_turns: int = 1
    last_error: str | None = None
    total_usage: dict[str, int] = None  # type: ignore[assignment]
    estimated_total_cost: float = 0.0

    def __post_init__(self) -> None:
        if self.total_usage is None:
            self.total_usage = {"input_tokens": 10, "output_tokens": 5, "cached_tokens": 0}


class _FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def render_help(self, commands) -> None:
        self.calls.append(("help", [command.name for command in commands]))

    def render_session(self, snapshot) -> None:
        self.calls.append(("session", snapshot.session_id))

    def render_history(self, messages, *, limit: int) -> None:
        self.calls.append(("history", limit, list(messages)))

    def render_debug_transcript(self, transcript: str) -> None:
        self.calls.append(("debug", transcript))

    def render_error(self, message: str) -> None:
        self.calls.append(("error", message))

    def render_note(self, message: str) -> None:
        self.calls.append(("note", message))

    def render_user_message(self, text: str) -> None:
        self.calls.append(("user", text))

    def render_event(self, event) -> None:
        self.calls.append(("event", event))


class _FakeEngine:
    def __init__(self) -> None:
        self.snapshot = _Snapshot()
        self.recent_messages = ["user:hello", "assistant:world"]
        self.last_user_prompt = "hello again"
        self.submitted_prompts: list[str] = []
        self.compact_instructions: str | None = None
        self.settings = SimpleNamespace(
            model=ModelSettings(),
        )
        self.llm = SimpleNamespace(api_key=None, base_url=None, model=None)

    def get_session_snapshot(self):
        return self.snapshot

    def get_recent_messages(self, limit: int = 10, *, include_meta: bool = False):
        del include_meta
        return self.recent_messages[-limit:]

    def transcript_preview(self) -> str:
        return "user: hello\nassistant: world"

    def get_last_user_prompt(self) -> str | None:
        return self.last_user_prompt

    async def submit_user_input(self, prompt: str):
        self.submitted_prompts.append(prompt)
        yield {"prompt": prompt}

    async def compact(self, custom_instructions: str | None = None):
        self.compact_instructions = custom_instructions
        return SimpleNamespace(
            compacted=True,
            pre_tokens=100,
            post_tokens=20,
            tokens_saved=80,
            reason="manual_compact",
            custom_instructions=custom_instructions,
        )


def test_parse_input_splits_command_args() -> None:
    parsed = parse_input("/history 5")

    assert parsed.kind == "command"
    assert parsed.command == "history"
    assert parsed.args == ["5"]


def test_controller_renders_help_and_session() -> None:
    controller = REPLController(_FakeEngine(), _FakeRenderer())
    renderer = controller.renderer

    asyncio.run(controller.handle(parse_input("/help")))
    asyncio.run(controller.handle(parse_input("/session")))

    assert renderer.calls[0] == (
        "help",
        [
            "help",
            "login",
            "compact",
            "session",
            "history",
            "retry",
            "debug",
            "clear",
            "exit",
            "quit",
        ],
    )
    assert renderer.calls[1] == ("session", "sess_test")


def test_controller_history_validates_count() -> None:
    controller = REPLController(_FakeEngine(), _FakeRenderer())
    renderer = controller.renderer

    asyncio.run(controller.handle(parse_input("/history nope")))
    asyncio.run(controller.handle(parse_input("/history 2")))

    assert renderer.calls[0] == ("error", "history count must be an integer")
    assert renderer.calls[1][0] == "history"
    assert renderer.calls[1][1] == 2


def test_controller_retry_resubmits_last_prompt() -> None:
    engine = _FakeEngine()
    renderer = _FakeRenderer()
    controller = REPLController(engine, renderer)

    asyncio.run(controller.handle(parse_input("/retry")))

    assert renderer.calls[0] == ("note", "retrying the most recent user prompt")
    assert renderer.calls[1] == ("event", {"prompt": "hello again"})
    assert engine.submitted_prompts == ["hello again"]


def test_controller_compact_passes_custom_instructions() -> None:
    engine = _FakeEngine()
    renderer = _FakeRenderer()
    controller = REPLController(engine, renderer)

    asyncio.run(controller.handle(parse_input("/compact focus on auth")))

    assert renderer.calls[0][0] == "note"
    assert "100 -> 20 tokens" in renderer.calls[0][1]
    assert engine.compact_instructions == "focus on auth"


def test_controller_does_not_echo_user_prompt() -> None:
    engine = _FakeEngine()
    renderer = _FakeRenderer()
    controller = REPLController(engine, renderer)

    asyncio.run(controller.handle(parse_input("hello")))

    assert ("user", "hello") not in renderer.calls
    assert renderer.calls == [("event", {"prompt": "hello"})]


class _FakePromptIO:
    async def secret(self, label: str, *, default: str | None = None) -> str:
        del label, default
        return "login-key"

    async def text(self, label: str, *, default: str | None = None) -> str:
        del default
        values = {
            "LLM provider": "openai-compatible",
            "LLM Base URL": "https://login.example.test/v1",
            "Swift model": "swift-model",
            "Balanced model": "balanced-model",
            "Depth model": "depth-model",
        }
        return values[label]

    async def choice(self, label: str, *, choices: tuple[str, ...], default: str) -> str:
        del label, choices, default
        return "depth"


def test_controller_login_saves_and_applies_user_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(tmp_path))
    engine = _FakeEngine()
    renderer = _FakeRenderer()
    controller = REPLController(engine, renderer, prompt_io=_FakePromptIO())

    asyncio.run(controller.handle(parse_input("/login")))

    saved_payload = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved_payload["provider"] == "openai-compatible"
    assert "system_prompt" not in saved_payload
    assert "model" not in saved_payload
    assert engine.settings.model.provider == "openai-compatible"
    assert engine.settings.model.api_key.get_secret_value() == "login-key"
    assert engine.settings.model.base_url == "https://login.example.test/v1"
    assert engine.settings.model.model == "depth-model"
    assert engine.llm.model == "depth-model"
    assert engine.submitted_prompts == []
