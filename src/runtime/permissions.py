from __future__ import annotations

import fnmatch
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from config.paths import get_siyi_config_home
from config.settings import ToolSettings
from tools.base import ToolContext
from tools.governance import PermissionResult


PermissionRequester = Callable[["PermissionRequest"], Awaitable[bool]]


class SandboxPolicy(BaseModel):
    enabled: bool = False
    fail_if_unavailable: bool = False
    allow_unsandboxed_commands: bool = True


class PermissionRules(BaseModel):
    allow: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class PermissionConfig(BaseModel):
    permissions: PermissionRules = Field(default_factory=PermissionRules)
    sandbox: SandboxPolicy = Field(default_factory=SandboxPolicy)
    source_path: Path | None = None


class PermissionRequest(BaseModel):
    tool_name: str
    tool_input: dict[str, Any]
    reason: str
    summary: str
    cwd: str


@dataclass(slots=True)
class PermissionManager:
    settings: ToolSettings
    config: PermissionConfig = field(default_factory=PermissionConfig)
    requester: PermissionRequester | None = None

    @classmethod
    def from_settings(
        cls,
        settings: ToolSettings,
        *,
        cwd: Path | None = None,
    ) -> "PermissionManager":
        config = load_permission_config(cwd)
        if config.source_path is None:
            config.sandbox = SandboxPolicy(
                enabled=settings.sandbox_enabled,
                fail_if_unavailable=settings.sandbox_fail_if_unavailable,
                allow_unsandboxed_commands=settings.allow_unsandboxed_commands,
            )
        return cls(settings=settings, config=config)

    def reload_for_cwd(self, cwd: Path) -> None:
        self.config = load_permission_config(cwd)

    def set_requester(self, requester: PermissionRequester | None) -> None:
        self.requester = requester

    def check(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PermissionResult:
        del context
        if self._is_shell_tool(tool_name, tool_input) and not self.settings.shell_enabled:
            return PermissionResult.deny(reason="shell tool is disabled", source="settings")
        if tool_name == "Read" and not self.settings.read_file_enabled:
            return PermissionResult.deny(reason="file reads are disabled", source="settings")
        if tool_name in {"WebSearch", "WebFetch", "web_search", "web_fetch"} and not self.settings.web_search_enabled:
            return PermissionResult.deny(reason="web tools are disabled", source="settings")

        sandbox_result = self._check_sandbox_policy(tool_name, tool_input)
        if sandbox_result.decision != "allow":
            return sandbox_result

        rule_result = self._check_rule_lists(tool_name, tool_input)
        if rule_result is not None:
            return rule_result

        return self._default_decision(tool_name, tool_input)

    async def authorize(
        self,
        tool: object,
        raw_input: dict[str, Any],
        context: ToolContext,
    ) -> PermissionResult:
        tool_name = str(getattr(tool, "name", ""))
        tool_decision = getattr(tool, "check_permissions")(raw_input, context)
        global_decision = self.check(tool_name, raw_input, {"cwd": context.cwd})
        decision = _combine_permissions(tool_decision, global_decision)
        if decision.decision != "ask":
            return decision

        if self.requester is None:
            return PermissionResult.deny(
                reason=f"permission required but no interactive approver is available: {decision.reason}",
                source=decision.source or "permission",
            )

        approved = await self.requester(
            PermissionRequest(
                tool_name=tool_name,
                tool_input=raw_input,
                reason=decision.reason or "permission required",
                summary=_tool_input_summary(tool_name, raw_input),
                cwd=context.cwd,
            )
        )
        if approved:
            return PermissionResult.allow(reason="approved for this tool call", source="interactive")
        return PermissionResult.deny(reason="user denied this tool call", source="interactive")

    def _check_rule_lists(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> PermissionResult | None:
        payload = _permission_payload(tool_name, tool_input)
        candidate = f"{tool_name}({payload})"
        for decision in ("deny", "allow", "ask"):
            rules = getattr(self.config.permissions, decision)
            for rule in rules:
                if _rule_matches(rule, tool_name, payload, candidate):
                    return PermissionResult(
                        decision=decision,
                        reason=f"matched permission rule: {rule}",
                        source=str(self.config.source_path or "default"),
                    )
        return None

    def _default_decision(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> PermissionResult:
        if self._is_shell_tool(tool_name, tool_input):
            if self.settings.shell_requires_approval:
                return PermissionResult.ask(reason="shell tool requires approval", source="default")
            return PermissionResult.allow(reason="shell tool allowed by settings", source="default")

        if _is_default_read_tool(tool_name, tool_input):
            return PermissionResult.allow(reason="read-only tool", source="default")
        return PermissionResult.ask(reason="tool can modify local state", source="default")

    def _check_sandbox_policy(self, tool_name: str, tool_input: dict[str, Any]) -> PermissionResult:
        if not self._is_shell_tool(tool_name, tool_input):
            return PermissionResult.allow(source="sandbox")
        policy = self.config.sandbox
        if not policy.enabled:
            return PermissionResult.allow(source="sandbox")
        if policy.allow_unsandboxed_commands:
            return PermissionResult.allow(
                reason="sandbox is configured but unsandboxed commands are allowed",
                source="sandbox",
            )
        if _native_windows():
            return PermissionResult.deny(
                reason=(
                    "sandbox is required, but native Windows PowerShell/Bash commands "
                    "cannot be isolated by SiYi v1"
                ),
                source="sandbox",
            )
        if policy.fail_if_unavailable:
            return PermissionResult.deny(
                reason="sandbox is required, but no sandbox backend is available",
                source="sandbox",
            )
        return PermissionResult.ask(
            reason="sandbox is unavailable; approve unsandboxed execution for this call",
            source="sandbox",
        )

    @staticmethod
    def _is_shell_tool(tool_name: str, tool_input: dict[str, Any] | None = None) -> bool:
        del tool_input
        return tool_name in {"shell", "Bash", "PowerShell", "ProcessStart"}


def load_permission_config(cwd: Path | None) -> PermissionConfig:
    project_path = (cwd / ".siyi" / "permissions.json") if cwd else None
    if project_path and project_path.exists():
        return _read_permission_config(project_path)

    global_path = get_siyi_config_home() / "permissions.json"
    if global_path.exists():
        return _read_permission_config(global_path)

    return PermissionConfig(
        permissions=PermissionRules(
            allow=[
                "Read(*)",
                "Glob(*)",
                "Grep(*)",
                "WebSearch(*)",
                "WebFetch(*)",
                "ToolSearch(*)",
                "ProcessRead(*)",
                "TaskGet(*)",
                "TaskList(*)",
                "Skill(*)",
                "ListMcpResourcesTool(*)",
                "ReadMcpResourceTool(*)",
                "AskUserQuestion(*)",
                "EnterPlanMode(*)",
                "ExitPlanMode(*)",
                "SendUserMessage(*)",
                "Config(get)",
                "Config(list)",
                "workflow(get)",
                "workflow(list)",
            ],
            ask=[
                "Bash(*)",
                "PowerShell(*)",
                "ProcessStart(*)",
                "ProcessWrite(*)",
                "ProcessStop(*)",
                "Write(*)",
                "Edit(*)",
                "NotebookEdit(*)",
                "Agent(*)",
                "SendMessage(*)",
                "TeamCreate(*)",
                "TeamDelete(*)",
                "TaskCreate(*)",
                "TaskUpdate(*)",
                "Config(set)",
                "Config(delete)",
                "workflow(run)",
            ],
        )
    )


def _read_permission_config(path: Path) -> PermissionConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raw = {}
    permissions_raw = raw.get("permissions")
    if permissions_raw is None:
        permissions_raw = {
            "allow": raw.get("allow", []),
            "ask": raw.get("ask", []),
            "deny": raw.get("deny", []),
        }
    sandbox_raw = raw.get("sandbox") or {}
    config = PermissionConfig(
        permissions=PermissionRules.model_validate(permissions_raw or {}),
        sandbox=SandboxPolicy.model_validate(sandbox_raw),
        source_path=path,
    )
    return config


def _combine_permissions(*results: PermissionResult) -> PermissionResult:
    denies = [result for result in results if result.decision == "deny"]
    if denies:
        return denies[0]
    asks = [result for result in results if result.decision == "ask"]
    if asks:
        return asks[0]
    return PermissionResult.allow(source="combined")


def _permission_payload(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name in {"Bash", "PowerShell", "ProcessStart", "shell"}:
        return str(tool_input.get("command") or "*")
    for key in ("action", "file_path", "path", "notebook_path", "uri", "query", "title", "task_id"):
        if key in tool_input and tool_input[key] is not None:
            return str(tool_input[key])
    return "*"


def _tool_input_summary(tool_name: str, tool_input: dict[str, Any]) -> str:
    payload = _permission_payload(tool_name, tool_input)
    if len(payload) > 240:
        payload = f"{payload[:240]}..."
    return f"{tool_name}({payload})"


def _rule_matches(rule: str, tool_name: str, payload: str, candidate: str) -> bool:
    rule = rule.strip()
    if not rule:
        return False
    if "(" not in rule or not rule.endswith(")"):
        return fnmatch.fnmatchcase(tool_name, rule) or fnmatch.fnmatchcase(candidate, rule)
    rule_tool, pattern = rule[:-1].split("(", 1)
    return fnmatch.fnmatchcase(tool_name, rule_tool) and fnmatch.fnmatchcase(payload, pattern)


def _is_default_read_tool(tool_name: str, tool_input: dict[str, Any]) -> bool:
    if tool_name in {
        "Read",
        "Glob",
        "Grep",
        "WebSearch",
        "WebFetch",
        "ToolSearch",
        "ProcessRead",
        "TaskGet",
        "TaskList",
        "Skill",
        "ListMcpResourcesTool",
        "ReadMcpResourceTool",
        "AskUserQuestion",
        "EnterPlanMode",
        "ExitPlanMode",
        "SendUserMessage",
    }:
        return True
    if tool_name == "Config":
        return str(tool_input.get("action") or "list") in {"get", "list"}
    if tool_name == "workflow":
        return str(tool_input.get("action") or "list") in {"get", "list"}
    return False


def _native_windows() -> bool:
    return sys.platform.startswith("win")
