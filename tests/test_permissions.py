from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.settings import ToolSettings
from engine.message_schema import ToolUseBlock
from engine.query_loop import _tool_batches
from runtime.permissions import PermissionManager
from tools.base import BaseTool, ToolContext, ToolResult
from tools.shell_analysis import analyze_bash, analyze_powershell
from tools.registry import ToolRegistry


class _DummyWriteTool(BaseTool):
    name = "Write"
    description = "dummy mutating tool"
    input_schema = {"type": "object", "properties": {}, "additionalProperties": True}

    async def run(self, raw_input, context: ToolContext) -> ToolResult:
        del raw_input
        return ToolResult(success=True, content=context.cwd)


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(cwd=str(tmp_path), trace_id="test")


def test_default_shell_permission_is_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(tmp_path / "global"))
    manager = PermissionManager.from_settings(ToolSettings(), cwd=tmp_path)

    result = manager.check("PowerShell", {"command": "Get-ChildItem"})

    assert result.decision == "ask"


def test_default_process_session_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(tmp_path / "global"))
    manager = PermissionManager.from_settings(ToolSettings(), cwd=tmp_path)

    assert manager.check("ProcessStart", {"command": "npm run dev"}).decision == "ask"
    assert manager.check("ProcessRead", {"process_id": "proc_test"}).decision == "allow"
    assert manager.check("ProcessWrite", {"process_id": "proc_test", "chars": "y\n"}).decision == "ask"
    assert manager.check("ProcessStop", {"process_id": "proc_test"}).decision == "ask"


def test_project_permission_config_wins_over_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "permissions.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(*)"]}}),
        encoding="utf-8",
    )
    project_dir = tmp_path / ".siyi"
    project_dir.mkdir()
    (project_dir / "permissions.json").write_text(
        json.dumps({"permissions": {"deny": ["Bash(*)"]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(global_dir))

    manager = PermissionManager.from_settings(ToolSettings(), cwd=tmp_path)
    result = manager.check("Bash", {"command": "git status"})

    assert result.decision == "deny"
    assert result.source == str(project_dir / "permissions.json")


def test_interactive_approval_is_current_call_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIYI_CONFIG_DIR", str(tmp_path / "global"))
    manager = PermissionManager.from_settings(ToolSettings(), cwd=tmp_path)
    approvals = 0

    async def approve_once(_request) -> bool:
        nonlocal approvals
        approvals += 1
        return True

    manager.set_requester(approve_once)

    import asyncio

    first = asyncio.run(manager.authorize(_DummyWriteTool(), {}, _context(tmp_path)))
    second = manager.check("Write", {})

    assert first.decision == "allow"
    assert second.decision == "ask"
    assert approvals == 1


def test_sandbox_required_on_native_windows_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / ".siyi"
    project_dir.mkdir()
    (project_dir / "permissions.json").write_text(
        json.dumps(
            {
                "sandbox": {
                    "enabled": True,
                    "allow_unsandboxed_commands": False,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("runtime.permissions.sys.platform", "win32")
    manager = PermissionManager.from_settings(ToolSettings(), cwd=tmp_path)

    result = manager.check("PowerShell", {"command": "Get-ChildItem"})

    assert result.decision == "deny"
    assert "native Windows" in (result.reason or "")


def test_shell_read_only_analysis_is_conservative() -> None:
    assert analyze_powershell("Get-ChildItem | Select-Object Name").read_only
    assert not analyze_powershell("New-Item test.txt").read_only
    assert analyze_bash("git status | head -n 5").read_only
    assert not analyze_bash("git status > out.txt").read_only


def test_tool_batches_group_consecutive_concurrency_safe_tools(tmp_path: Path) -> None:
    registry = ToolRegistry.default(PermissionManager.from_settings(ToolSettings(), cwd=tmp_path))
    context = _context(tmp_path)

    batches = _tool_batches(
        [
            ToolUseBlock(name="Read", input={"file_path": "a.txt"}),
            ToolUseBlock(name="Glob", input={"pattern": "*.txt"}),
            ToolUseBlock(name="Write", input={"file_path": "a.txt", "content": "x"}),
            ToolUseBlock(name="Grep", input={"pattern": "x"}),
        ],
        registry,
        context,
    )

    assert [len(batch.blocks) for batch in batches] == [2, 1, 1]
    assert [batch.concurrent for batch in batches] == [True, False, True]
