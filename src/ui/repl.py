from __future__ import annotations

from prompt_toolkit import PromptSession

from engine.query_engine import QueryEngine
from ui.input_parser import parse_input
from ui.renderer import ConsoleRenderer


async def run_repl(engine: QueryEngine, renderer: ConsoleRenderer) -> None:
    session: PromptSession[str] = PromptSession()
    renderer.console.print("[bold]General Agent (将军)[/bold] type /exit to quit")

    while True:
        try:
            raw = await session.prompt_async("general> ")
        except (EOFError, KeyboardInterrupt):
            renderer.console.print()
            return

        parsed = parse_input(raw)
        if parsed.kind == "empty":
            continue
        if parsed.kind == "command":
            if parsed.command in {"exit", "quit"}:
                return
            if parsed.command == "clear":
                renderer.console.clear()
                continue
            if parsed.command == "debug":
                renderer.console.print(engine.transcript_preview() or "(no messages)")
                continue
            renderer.render_error(f"unknown command: /{parsed.command}")
            continue

        renderer.render_user_message(parsed.text)
        async for event in engine.submit_user_input(parsed.text):
            renderer.render_event(event)
