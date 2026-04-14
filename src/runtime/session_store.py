from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.message_schema import Message
from runtime.ids import new_id

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionHandle:
    session_id: str
    path: Path
    messages: list[Message]


class JsonlSessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def open_session(
        self,
        requested_session: str | bool | None,
        cwd: Path,
    ) -> SessionHandle:
        if requested_session:
            session_id = self._resolve_requested_session(requested_session)
            path = self.root / f"{session_id}.jsonl"
            messages = self.load_messages(session_id) if path.exists() else []
            LOGGER.info(
                "session.opened",
                extra={
                    "session_id": session_id,
                    "resumed": path.exists(),
                    "cwd": str(cwd),
                },
            )
            return SessionHandle(session_id=session_id, path=path, messages=messages)

        session_id = new_id("sess")
        path = self.root / f"{session_id}.jsonl"
        LOGGER.info(
            "session.created",
            extra={"session_id": session_id, "cwd": str(cwd)},
        )
        return SessionHandle(session_id=session_id, path=path, messages=[])

    def append_message(self, session: SessionHandle, message: Message) -> None:
        session.messages.append(message)
        self._append_entry(
            session.path,
            {
                "kind": "message",
                "session_id": session.session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": message.model_dump(mode="json"),
            },
        )

    def append_messages(self, session: SessionHandle, messages: list[Message]) -> None:
        for message in messages:
            self.append_message(session, message)

    def append_event(self, session: SessionHandle, event: Any) -> None:
        payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
        self._append_entry(
            session.path,
            {
                "kind": "event",
                "session_id": session.session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": payload,
            },
        )

    def load_messages(self, session_id: str) -> list[Message]:
        path = self.root / f"{session_id}.jsonl"
        if not path.exists():
            return []

        messages: list[Message] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("kind") == "message":
                    messages.append(Message.model_validate(entry["message"]))
        return messages

    def list_sessions(self) -> list[str]:
        return sorted(
            (path.stem for path in self.root.glob("*.jsonl")),
            key=lambda session_id: (self.root / f"{session_id}.jsonl").stat().st_mtime,
            reverse=True,
        )

    def _append_entry(self, path: Path, entry: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False))
            handle.write("\n")

    def _resolve_requested_session(self, requested_session: str | bool) -> str:
        if isinstance(requested_session, str):
            return (
                Path(requested_session).stem
                if requested_session.endswith(".jsonl")
                else requested_session
            )

        latest = max(
            self.root.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            default=None,
        )
        return latest.stem if latest is not None else new_id("sess")
