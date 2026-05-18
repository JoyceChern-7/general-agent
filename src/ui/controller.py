from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from config.paths import get_user_settings_path
from config.user_settings import (
    DEFAULT_MODEL_TIERS,
    MODEL_TIER_LABELS,
    UserModelTier,
    UserSettings,
    default_user_settings,
    load_user_settings,
    save_user_settings,
)
from engine.query_engine import QueryEngine
from runtime.permissions import PermissionRequest
from ui.input_parser import ParsedInput
from ui.prompt_io import PromptIO
from ui.renderer import ConsoleRenderer


@dataclass(slots=True)
class CommandSpec:
    name: str
    usage: str
    description: str


class REPLController:
    def __init__(
        self,
        engine: QueryEngine,
        renderer: ConsoleRenderer,
        prompt_io: PromptIO | None = None,
    ) -> None:
        self.engine = engine
        self.renderer = renderer
        self.prompt_io = prompt_io
        permission_manager = getattr(self.engine, "permission_manager", None)
        if self.prompt_io is not None and permission_manager is not None:
            permission_manager.set_requester(self._ask_permission)
        self.command_specs = [
            CommandSpec("help", "/help", "Show the available REPL commands."),
            CommandSpec("login", "/login", "Configure LLM API settings."),
            CommandSpec("compact", "/compact [instructions]", "Compact the current session context."),
            CommandSpec("session", "/session", "Show the current session summary."),
            CommandSpec("history", "/history [count]", "Show recent transcript messages."),
            CommandSpec("retry", "/retry", "Resubmit the most recent user prompt."),
            CommandSpec("debug", "/debug", "Print a plain-text transcript preview."),
            CommandSpec("clear", "/clear", "Clear the terminal output."),
            CommandSpec("exit", "/exit", "Exit the REPL."),
            CommandSpec("quit", "/quit", "Exit the REPL."),
        ]

    def show_welcome(self) -> None:
        snapshot = self.engine.get_session_snapshot()
        self.renderer.render_welcome(
            session_id=snapshot.session_id,
            cwd=snapshot.cwd,
            model=snapshot.model,
        )

    async def handle(self, parsed: ParsedInput) -> bool:
        if parsed.kind == "empty":
            return True
        if parsed.kind == "command":
            return await self._handle_command(parsed)
        await self._submit_prompt(parsed.text)
        return True

    async def _handle_command(self, parsed: ParsedInput) -> bool:
        assert parsed.command is not None
        command = parsed.command.lower()

        if command in {"exit", "quit"}:
            return False
        if command == "clear":
            self.renderer.console.clear()
            return True
        if command == "help":
            self.renderer.render_help(self.command_specs)
            return True
        if command == "login":
            await self._handle_login()
            return True
        if command == "compact":
            await self._handle_compact(parsed.args)
            return True
        if command == "session":
            self.renderer.render_session(self.engine.get_session_snapshot())
            return True
        if command == "history":
            return self._handle_history(parsed.args)
        if command == "debug":
            self.renderer.render_debug_transcript(self.engine.transcript_preview())
            return True
        if command == "retry":
            prompt = self.engine.get_last_user_prompt()
            if prompt is None:
                self.renderer.render_error("no previous user prompt is available to retry")
                return True
            self.renderer.render_note("retrying the most recent user prompt")
            await self._submit_prompt(prompt)
            return True

        self.renderer.render_error(f"unknown command: /{parsed.command}")
        return True

    def _handle_history(self, args: list[str]) -> bool:
        if len(args) > 1:
            self.renderer.render_error("usage: /history [count]")
            return True

        limit = 10
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                self.renderer.render_error("history count must be an integer")
                return True
            if limit <= 0:
                self.renderer.render_error("history count must be greater than zero")
                return True

        self.renderer.render_history(
            self.engine.get_recent_messages(limit=limit),
            limit=limit,
        )
        return True

    async def _submit_prompt(self, prompt: str) -> None:
        async for event in self.engine.submit_user_input(prompt):
            self.renderer.render_event(event)

    async def _handle_compact(self, args: list[str]) -> None:
        instructions = " ".join(args).strip() or None
        try:
            result = await self.engine.compact(instructions)
        except Exception as exc:  # noqa: BLE001 - surface compact failures in the REPL
            self.renderer.render_error(f"compact failed: {exc}")
            return
        if not result.compacted:
            self.renderer.render_note(f"compact skipped: {result.reason or 'not needed'}")
            return
        self.renderer.render_note(
            "compacted context: "
            f"{result.pre_tokens} -> {result.post_tokens} tokens, "
            f"saved ~{result.tokens_saved}"
        )

    async def _ask_permission(self, request: PermissionRequest) -> bool:
        if self.prompt_io is None:
            return False
        self.renderer.render_note(
            f"permission request: {request.summary}\n"
            f"reason: {request.reason}\n"
            f"cwd: {request.cwd}"
        )
        choice = await self.prompt_io.choice(
            "Allow this tool call",
            choices=("yes", "no"),
            default="no",
        )
        return choice == "yes"

    async def _handle_login(self) -> None:
        if self.prompt_io is None:
            self.renderer.render_error("/login is only available in interactive mode")
            return

        existing = load_user_settings()
        defaults = default_user_settings()
        merged_models = {
            **defaults.models,
            **existing.models,
        }
        self.renderer.render_note("SiYi API setup: LLM")
        provider = await self.prompt_io.text("LLM provider", default=existing.provider)
        api_key = await self.prompt_io.secret("LLM API Key", default=existing.api_key)
        base_url = await self.prompt_io.text("LLM Base URL", default=existing.base_url)

        configured_models: dict[str, UserModelTier] = {}
        for tier, fallback_model in DEFAULT_MODEL_TIERS.items():
            current = merged_models.get(tier)
            label = MODEL_TIER_LABELS[tier]
            model = await self.prompt_io.text(
                f"{label} model",
                default=current.model if current else fallback_model,
            )
            configured_models[tier] = UserModelTier(label=label, model=model)

        default_tier = await self.prompt_io.choice(
            "Default tier",
            choices=("swift", "balanced", "depth"),
            default=existing.default_tier if existing.default_tier in DEFAULT_MODEL_TIERS else "balanced",
        )

        settings = UserSettings(
            provider=provider or "openai-compatible",
            api_key=api_key,
            base_url=base_url or None,
            default_tier=default_tier,
            models=configured_models,
        )
        path = save_user_settings(settings, get_user_settings_path())
        self._apply_login_settings(settings)
        self.renderer.render_note(f"saved API settings to {path}")

    def _apply_login_settings(self, settings: UserSettings) -> None:
        selected_model = settings.models[settings.default_tier].model
        api_key = SecretStr(settings.api_key) if settings.api_key else None
        self.engine.settings.model = self.engine.settings.model.model_copy(
            update={
                "provider": settings.provider,
                "api_key": api_key,
                "base_url": settings.base_url,
                "model": selected_model,
            }
        )
        if hasattr(self.engine.llm, "api_key"):
            self.engine.llm.api_key = api_key
        if hasattr(self.engine.llm, "base_url"):
            self.engine.llm.base_url = settings.base_url
        if hasattr(self.engine.llm, "model"):
            self.engine.llm.model = selected_model
