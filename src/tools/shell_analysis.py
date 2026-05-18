from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePath


@dataclass(frozen=True, slots=True)
class ShellAnalysisResult:
    read_only: bool
    reason: str
    parser: str


_BASH_REJECT_RE = re.compile(
    r"(\$\(|`|<\(|>\(|\b(eval|exec|source|sudo|su|chmod|chown|rm|mv|cp|mkdir|rmdir|touch|tee)\b)"
)
_BASH_CONTROL_RE = re.compile(r"(&&|\|\||;|\n)")
_BASH_REDIRECT_RE = re.compile(r"(^|\s)(>|>>|<|<<|<<<|2>|2>>|&>|&>>)(\s|$)")

_POWERSHELL_REJECT_RE = re.compile(
    r"(\$\w+\s*=|[{};]|&&|\|\||>>?|<|`|"
    r"\b(Set|New|Remove|Clear|Start|Stop|Restart|Invoke|Import|Export|Out-File|"
    r"Tee-Object|Add|Copy|Move|Rename|Compress|Expand)-)",
    re.IGNORECASE,
)

_READ_ONLY_BASH = {
    "basename",
    "cat",
    "cut",
    "date",
    "dirname",
    "du",
    "echo",
    "env",
    "find",
    "git",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "sed",
    "sort",
    "tail",
    "test",
    "type",
    "uname",
    "uniq",
    "wc",
    "where",
    "which",
}

_READ_ONLY_GIT = {
    "blame",
    "branch",
    "describe",
    "diff",
    "grep",
    "log",
    "ls-files",
    "remote",
    "rev-parse",
    "show",
    "status",
    "tag",
}

_READ_ONLY_POWERSHELL_VERBS = {
    "compare",
    "convertfrom",
    "convertto",
    "format",
    "get",
    "measure",
    "out",
    "resolve",
    "select",
    "sort",
    "split",
    "test",
    "where",
    "write",
}

_READ_ONLY_POWERSHELL_ALIASES = {
    "cat",
    "cd",
    "dir",
    "echo",
    "findstr",
    "gc",
    "gci",
    "git",
    "ls",
    "pwd",
    "rg",
    "select",
    "type",
    "where",
}


@lru_cache(maxsize=8)
def _tree_sitter_parser(language: str) -> object | None:
    try:
        from tree_sitter_language_pack import get_parser
    except Exception:
        return None
    try:
        return get_parser(language)
    except Exception:
        return None


def _tree_sitter_accepts(language: str, command: str) -> bool:
    parser = _tree_sitter_parser(language)
    if parser is None:
        return True
    try:
        tree = parser.parse(command.encode("utf-8"))
    except Exception:
        return False
    return not bool(getattr(tree.root_node, "has_error", False))


def _basename(command: str) -> str:
    return PurePath(command.strip().strip("\"'")).name.lower()


def _split_pipeline(command: str) -> list[str]:
    return [segment.strip() for segment in command.split("|") if segment.strip()]


def analyze_bash(command: str) -> ShellAnalysisResult:
    command = command.strip()
    if not command:
        return ShellAnalysisResult(False, "empty command", "bash")
    if not _tree_sitter_accepts("bash", command):
        return ShellAnalysisResult(False, "bash parser rejected the command", "tree-sitter:bash")
    if _BASH_CONTROL_RE.search(command):
        return ShellAnalysisResult(False, "bash control operators require approval", "bash")
    if _BASH_REDIRECT_RE.search(command):
        return ShellAnalysisResult(False, "redirection requires approval", "bash")
    if _BASH_REJECT_RE.search(command):
        return ShellAnalysisResult(False, "mutating or dynamic bash construct requires approval", "bash")

    for segment in _split_pipeline(command):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError as exc:
            return ShellAnalysisResult(False, f"could not parse bash segment: {exc}", "bash")
        if not tokens:
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
            return ShellAnalysisResult(False, "environment assignment requires approval", "bash")
        executable = _basename(tokens[0])
        if executable not in _READ_ONLY_BASH:
            return ShellAnalysisResult(False, f"{executable} is not classified read-only", "bash")
        if executable == "git" and not _git_is_read_only(tokens[1:]):
            return ShellAnalysisResult(False, "git subcommand is not classified read-only", "bash")
        if executable == "find" and any(token in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for token in tokens[1:]):
            return ShellAnalysisResult(False, "find action is not read-only", "bash")
        if executable == "sed" and any(token.startswith("-i") for token in tokens[1:]):
            return ShellAnalysisResult(False, "sed in-place edit is not read-only", "bash")
    return ShellAnalysisResult(True, "all bash segments are read-only", "bash")


def analyze_powershell(command: str) -> ShellAnalysisResult:
    command = command.strip()
    if not command:
        return ShellAnalysisResult(False, "empty command", "powershell")
    if not _tree_sitter_accepts("powershell", command):
        return ShellAnalysisResult(False, "PowerShell parser rejected the command", "tree-sitter:powershell")
    if _POWERSHELL_REJECT_RE.search(command):
        return ShellAnalysisResult(False, "mutating or dynamic PowerShell construct requires approval", "powershell")

    for segment in _split_pipeline(command):
        tokens = _split_powershell_segment(segment)
        if not tokens:
            continue
        executable = tokens[0].lower()
        if executable == "git":
            if not _git_is_read_only(tokens[1:]):
                return ShellAnalysisResult(False, "git subcommand is not classified read-only", "powershell")
            continue
        if executable in _READ_ONLY_POWERSHELL_ALIASES:
            continue
        if "-" in executable:
            verb = executable.split("-", 1)[0]
            if verb in _READ_ONLY_POWERSHELL_VERBS:
                continue
        return ShellAnalysisResult(False, f"{tokens[0]} is not classified read-only", "powershell")
    return ShellAnalysisResult(True, "all PowerShell segments are read-only", "powershell")


def _split_powershell_segment(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=False)
    except ValueError:
        return [part for part in re.split(r"\s+", segment.strip()) if part]


def _git_is_read_only(args: list[str]) -> bool:
    for arg in args:
        if not arg.startswith("-"):
            return arg in _READ_ONLY_GIT
    return False
