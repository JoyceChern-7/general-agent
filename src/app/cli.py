"""
数据结构:
argv: Sequence[str], 代表命令行参数列表, 例如 ["--model", "gpt-4", "--system-prompt", "You are a helpful assistant"]

namespace: 一个 argparse.ArgumentParser 用于解析命令行参数并将它们转换为 CLIOptions 对象.
解析命令行中的以下参数:
- prompt: string(可选), 如果省略，则启动 REPL(交互模式)，除非 stdin 被管道输入.
- model: string(可选)，表示主代理循环使用的模型名称.
- system-prompt: string(可选)，覆盖此会话的默认系统提示
- resume: string or bool(可选)，如果提供了 id, 则表示通过 id 恢复先前的会话, 如果没有提供 id, 则恢复最新的会话, 如果没有提供参数，则不恢复任何会话.
- debug: bool(可选)，表示是否启用调试日志记录.
- print-thinking: bool(可选),表示是否打印model的CoT.
- cwd: Path(可选)，工具和会话上下文的工作目录.
- non-interactive: bool(可选)，表示是否运行单个提示并退出.
- version: 显示版本信息并退出.

CLIOptions: 一个 dataclass, 包含从命令行参数解析的选项字段.
包含以下字段:
- prompt: string(可选)，非交互模式下要运行的提示.
- model: string(可选)，主代理循环使用的模型名称.
- system_prompt: string(可选)，覆盖此会话的默认系统提示.
- resume: string or bool(可选)，如果提供了 id, 则表示通过 id 恢复先前的会话, 如果没有提供 id, 则恢复最新的会话, 如果没有提供参数，则不恢复任何会话.
- debug: bool(可选)，表示是否启用调试日志记录.
- print_thinking: bool(可选), 表示是否打印model的CoT.
- cwd: Path(可选)，工具和会话上下文的工作目录.
- non_interactive: bool(可选)，表示是否运行单个提示并退出.


workflow:
0. 输入: 用户通过命令行提供参数.
1. 解析命令行参数, 然后创建 CLIOptions 对象.
2. 如果没有提供 prompt 参数, 则尝试从管道输入读取提示.
3. 将解析后的选项传递给 app.main.run 函数, 该函数负责设置应用程序运行时环境并执行主逻辑.
4. 根据运行结果返回适当的退出代码.

dataflow:
输入: 用户输入命令行参数 argv
-> build_parser() 创建 ArgumentParser
-> parse_args(argv) 解析参数, 创建 CLIOptions对象, 并传递给 _merge_stdin_prompt()
-> _merge_stdin_prompt() 接受CLIOptions对象, 如果没有提供 prompt 参数, 则尝试从管道输入读取提示并合并到 CLIOptions 中, 将更新后的 CLIOptions 对象传递给main() 
-> main() 传递 CLIOptions option 给 app.main.run 
-> (app.main.run 设置运行时环境并执行主逻辑) 
-> 返回退出代码
例如: general-agent --model gpt-4 --system-prompt "You are a helpful assistant"
-> build_parser() 创建 ArgumentParser
-> parse_args(argv) 解析参数得到 CLIOptions(prompt=None, model="gpt-4", system_prompt="You are a helpful assistant", resume=None, debug=False, print_thinking=False, cwd=None, non_interactive=False)
-> _merge_stdin_prompt() 因为 prompt 是 None, 尝试从管道输入读取提示, 假设没有管道输入, 则传递原来的 CLIOptions 对象给 main()
-> main() 传递 CLIOptions 对象给 app.main.run(options)

为什么要引入 CLIOptions 这个数据结构? 而不直接使用 argparse.Namespace 或者字典来存储解析后的命令行参数呢?
引入 CLIOptions 数据结构的主要原因是为了更清晰地组织和管理从命令行解析得到的选项。
CLIOptions 作为一个 dataclass, 提供了一个明确的结构来存储和访问这些选项，使得代码更易读和维护。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Sequence

from app.options import CLIOptions

VERSION = "0.1.0"



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="general-agent",
        description="Run the General Agent (将军) command line interface.",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Prompt to run in non-interactive mode. If omitted, starts the REPL unless stdin is piped.",
    )
    parser.add_argument("--model", help="Model name for the main agent loop.")
    parser.add_argument("--system-prompt", help="Override the default system prompt for this session.")
    parser.add_argument(
        "--resume",
        nargs="?", # 表示这个参数是可选的
        const=True, # 如果用户提供了 --resume 但没有跟随一个值，则 resume 的值将是 True，表示恢复最新的会话
        default=None, # 如果用户没有提供 --resume 参数，则 resume 的值将是 None，表示不恢复任何会话
        help="Resume a previous session by id. If no id is supplied, resume the latest session.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "--print-thinking",
        action="store_true",
        help="Print thinking events when the model provider emits them.",
    )
    parser.add_argument("--cwd", type=Path, help="Working directory for tools and session context.")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run a single prompt and exit. Piped stdin also enables this mode.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CLIOptions:
    namespace = build_parser().parse_args(argv)
    cwd = namespace.cwd.expanduser().resolve() if namespace.cwd else None
    return CLIOptions(
        prompt=namespace.prompt,
        model=namespace.model,
        system_prompt=namespace.system_prompt,
        resume=namespace.resume,
        debug=namespace.debug,
        print_thinking=namespace.print_thinking,
        cwd=cwd,
        non_interactive=namespace.non_interactive,
    )


def _read_piped_stdin() -> str | None:
    if sys.stdin is None or sys.stdin.isatty():
        return None
    value = sys.stdin.read().strip()
    return value or None 
# return None if the input is empty "", 
# or return the string value if it's not empty


def _merge_stdin_prompt(options: CLIOptions) -> CLIOptions:
    if options.prompt:
        return options
    # return early if a prompt is already provided via CLI args, 
    # since piped stdin should not override it
    stdin_prompt = _read_piped_stdin()
    if not stdin_prompt:
        return options
    # if there is no prompt from CLI args,
    # we try to read from piped stdin. 
    # If we get a non-empty prompt from stdin, 
    # merge it into the options and enable non-interactive mode
    return CLIOptions(
        prompt=stdin_prompt,
        model=options.model,
        system_prompt=options.system_prompt,
        resume=options.resume,
        debug=options.debug,
        print_thinking=options.print_thinking,
        cwd=options.cwd,
        non_interactive=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    if os.name == "nt":
        os.environ.setdefault("NoDefaultCurrentDirectoryInExePath", "1")
    # nt refers to "Windows", 
    # and this environment variable prevents the current directory from being added to the PATH when running executables, 
    # which can cause issues with finding dependencies. 
    # Setting it to "1" opts into the new behavior where the current directory is not included in the PATH by default.
    from app.main import run

    options = _merge_stdin_prompt(parse_args(argv))
    return asyncio.run(run(options))


if __name__ == "__main__":
    raise SystemExit(main())
