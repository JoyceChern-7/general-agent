from __future__ import annotations

from rich.console import Console
from rich.text import Text

from engine.events import (
    AssistantDeltaEvent,
    AssistantDoneEvent,
    ErrorEvent,
    FinalAnswerEvent,
    QueryEvent,
    StatusEvent,
    ToolResultEvent,
    ToolUseEvent,
)


class ConsoleRenderer:
    def __init__(self, debug: bool = False, print_thinking: bool = False) -> None:
        self.console = Console()
        self.debug = debug
        self.print_thinking = print_thinking
        self._assistant_open = False

    def render_event(self, event: QueryEvent) -> None:
        if isinstance(event, StatusEvent):
            self.render_status(event.message)
        elif isinstance(event, AssistantDeltaEvent):
            self.render_assistant_delta(event.delta)
        elif isinstance(event, AssistantDoneEvent):
            self.render_assistant_done()
        elif isinstance(event, ToolUseEvent):
            self.render_tool_use(event)
        elif isinstance(event, ToolResultEvent):
            self.render_tool_result(event)
        elif isinstance(event, FinalAnswerEvent):
            self.render_final(event)
        elif isinstance(event, ErrorEvent):
            self.render_error(event.message)

    def render_user_message(self, text: str) -> None:
        self.console.print(Text(f"> {text}", style="bold cyan"))

    def render_assistant_delta(self, delta: str) -> None:
        if not self._assistant_open:
            self.console.print(Text("assistant: ", style="bold green"), end="")
            self._assistant_open = True
        self.console.print(delta, end="")

    def render_assistant_done(self) -> None:
        if self._assistant_open:
            self.console.print()
            self._assistant_open = False

    def render_tool_use(self, event: ToolUseEvent) -> None:
        self.console.print(f"[yellow]tool_use[/yellow] {event.block.name} {event.block.input}")

    def render_tool_result(self, event: ToolResultEvent) -> None:
        style = "red" if event.block.is_error else "green"
        self.console.print(f"[{style}]tool_result[/{style}] {event.block.content}")

    def render_status(self, message: str) -> None:
        if self.debug:
            self.console.print(f"[dim]{message}[/dim]")

    def render_final(self, event: FinalAnswerEvent) -> None:
        if self.debug and event.usage:
            self.console.print(f"[dim]usage={event.usage.model_dump()}[/dim]")

    def render_error(self, message: str) -> None:
        self.render_assistant_done()
        self.console.print(f"[bold red]error:[/bold red] {message}")
