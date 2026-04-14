from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from config.settings import AppSettings
from engine.events import (
    ErrorEvent,
    FinalAnswerEvent,
    QueryEvent,
    StatusEvent,
)
from engine.message_schema import (
    Message,
    TextBlock,
    get_messages_after_compact_boundary,
    normalize_messages_for_api,
    user_message,
)
from engine.query_loop import DefaultQueryLoop, QueryLoop
from engine.turn_state import QueryTurnState
from llm.base import LLMAdapter
from runtime.compaction import CompactionManager
from runtime.permissions import PermissionManager
from runtime.session_store import JsonlSessionStore, SessionHandle
from runtime.token_budget import BudgetSnapshot, TokenBudget
from runtime.usage_tracker import UsageTracker
from tools.registry import ToolRegistry

LOGGER = logging.getLogger(__name__)


class QueryEngine:
    def __init__(
        self,
        session: SessionHandle,
        settings: AppSettings,
        llm: LLMAdapter,
        tool_registry: ToolRegistry,
        session_store: JsonlSessionStore, 
        # why JsonlSessionStore? 
        # Because we want to persist the session data in a jsonl file, so that we can load it later and continue the session. 
        # This is also useful for debugging and auditing purposes.
        permission_manager: PermissionManager,
        compaction_manager: CompactionManager,
        token_budget: TokenBudget,
        usage_tracker: UsageTracker,
        query_loop: QueryLoop | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.llm = llm
        self.tool_registry = tool_registry
        self.session_store = session_store
        self.permission_manager = permission_manager
        self.compaction_manager = compaction_manager
        self.token_budget = token_budget
        self.usage_tracker = usage_tracker
        self.query_loop = query_loop or DefaultQueryLoop()
        self.mutable_messages: list[Message] = list(session.messages)
        self.last_error: str | None = None
        self.last_turn: QueryTurnState | None = None
        self.turn_counter = self._derive_turn_counter()

    async def submit_user_input(self, text: str) -> AsyncIterator[QueryEvent]:
        prompt = text.strip() 
        if not prompt:
            self.last_error = "empty_prompt"
            error = ErrorEvent(
                session_id=self.session.session_id,
                message="Prompt is empty.",
                retryable=False,
                code="empty_prompt",
            )
            self.session_store.append_event(self.session, error)
            yield error
            return

        self.last_error = None
        user_msg = self._build_user_message(prompt)
        turn = self._create_turn_state(prompt, user_msg)
        self.last_turn = turn

        self._append_message(user_msg)
        yield self._status(
            turn,
            f"session={self.session.session_id}",
            code="session_ready",
            persisted_messages=len(self.mutable_messages),
        )
        yield self._status(
            turn,
            f"turn={turn.turn_index}",
            code="turn_started",
            turn_id=turn.turn_id,
        )

        budget = self._prepare_turn(turn)
        yield self._status(
            turn,
            f"estimated_tokens={budget.estimated_tokens}",
            code="budget_estimate",
            estimated_tokens=budget.estimated_tokens,
            remaining_input_budget=budget.remaining_input_budget,
        )

        if budget.should_warn:
            yield self._status(
                turn,
                "request is approaching the configured context budget",
                code="budget_warning",
                estimated_tokens=budget.estimated_tokens,
                warning_threshold=budget.warning_threshold,
            )

        if budget.should_autocompact:
            yield self._status(
                turn,
                "request crossed the auto-compaction threshold",
                code="autocompact_recommended",
                estimated_tokens=budget.estimated_tokens,
                autocompact_threshold=budget.autocompact_threshold,
            )

        if budget.is_blocking_limit:
            turn.mark_failed("token_budget_exceeded", retryable=False)
            self.last_error = turn.error
            error = ErrorEvent(
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                message=(
                    "request would exceed token budget: "
                    f"estimated={budget.estimated_tokens}, "
                    f"blocking_limit={budget.blocking_limit}"
                ),
                retryable=False,
                code="token_budget_exceeded",
            )
            self.session_store.append_event(self.session, error)
            yield error
            return

        persisted_generated_count = 0
        try:
            async for event in self.query_loop.run(
                turn,
                llm=self.llm,
                system_prompt=self.settings.model.system_prompt,
                tools=self.tool_registry.to_model_tool_schemas(),
                temperature=self.settings.model.temperature,
            ):
                persisted_generated_count = self._drain_generated_messages(
                    turn,
                    persisted_generated_count,
                )
                emitted = self._attach_turn_metadata(event, turn)
                self._persist_event(emitted)
                yield emitted 
        except Exception as exc:  # noqa: BLE001
            if self.settings.runtime.debug:
                LOGGER.exception("query_engine.turn_failed")
            else:
                LOGGER.debug("query_engine.turn_failed", exc_info=exc)
            turn.mark_failed(type(exc).__name__, retryable=False)
            self.last_error = turn.error
            error = ErrorEvent(
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                message=str(exc),
                retryable=False,
                code=type(exc).__name__,
            )
            self.session_store.append_event(self.session, error)
            yield error
            return

        persisted_generated_count = self._drain_generated_messages(
            turn,
            persisted_generated_count,
        )
        turn.mark_completed(turn.stop_reason)

        usage_snapshot = self.usage_tracker.record_turn(turn.turn_id, turn.usage_delta)
        final_message = turn.final_message or self._build_fallback_final_message()
        final_event = FinalAnswerEvent(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            message=final_message,
            usage=self.usage_tracker.get_total_usage(),
            estimated_cost=usage_snapshot.estimated_cost,
        )
        self.session_store.append_event(self.session, final_event)
        yield final_event

    def _build_user_message(self, text: str) -> Message:
        return user_message(text)

    def _create_turn_state(self, prompt: str, user_msg: Message) -> QueryTurnState:
        self.turn_counter += 1
        prior_messages = list(self.mutable_messages)
        return QueryTurnState(
            session_id=self.session.session_id,
            turn_index=self.turn_counter,
            user_message=user_msg,
            prompt_text=prompt,
            max_turns=self.settings.runtime.max_turns,
            messages=[*prior_messages, user_msg],
        )

    def _prepare_turn(self, turn: QueryTurnState) -> BudgetSnapshot:
        turn.stage = "preflight"
        compaction_result = self.compaction_manager.maybe_compact(turn.messages)
        turn.messages_for_query = normalize_messages_for_api(
            get_messages_after_compact_boundary(compaction_result.messages),
        )
        budget = self.token_budget.evaluate(
            messages=turn.messages_for_query,
            system_prompt=self.settings.model.system_prompt,
            tools=self.tool_registry.to_model_tool_schemas(),
        )
        turn.estimated_input_tokens = budget.estimated_tokens
        return budget

    def _append_message(self, message: Message) -> None:
        self.mutable_messages.append(message)
        self.session_store.append_message(self.session, message)

    def _drain_generated_messages(
        self,
        turn: QueryTurnState,
        already_persisted: int,
    ) -> int:
        pending = turn.generated_messages[already_persisted:]
        if not pending:
            return already_persisted
        for message in pending:
            self.mutable_messages.append(message)
            self.session_store.append_message(self.session, message)
        return len(turn.generated_messages)

    def _attach_turn_metadata(
        self,
        event: QueryEvent,
        turn: QueryTurnState,
    ) -> QueryEvent:
        update: dict[str, str] = {}
        if event.session_id is None:
            update["session_id"] = turn.session_id
        if event.turn_id is None:
            update["turn_id"] = turn.turn_id
        return event.model_copy(update=update) if update else event

    def _persist_event(self, event: QueryEvent) -> None:
        if event.type == "assistant_delta":
            return
        self.session_store.append_event(self.session, event)

    def _status(
        self,
        turn: QueryTurnState,
        message: str,
        *,
        code: str,
        **details: object,
    ) -> StatusEvent:
        event = StatusEvent(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            message=message,
            code=code,
            details={key: value for key, value in details.items()},
        )
        self.session_store.append_event(self.session, event)
        return event

    def _build_fallback_final_message(self) -> Message:
        return Message(
            type="assistant",
            role="assistant",
            content=[TextBlock(text="(no final assistant message was produced)")],
            is_meta=True,
        )

    def _derive_turn_counter(self) -> int:
        return sum(
            1
            for message in self.mutable_messages
            if message.role == "user"
            and not message.is_meta
            and not message.has_tool_result()
        )

    def transcript_preview(self) -> str:
        return "\n".join(
            f"{message.role}: {message.to_plain_text()}"
            for message in self.mutable_messages
            if any(isinstance(block, TextBlock) for block in message.content)
        )

    def get_messages(self) -> list[Message]:
        return list(self.mutable_messages)
