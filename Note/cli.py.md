
数据结构:

argv: Sequence[str], 代表命令行参数列表, 例如 
["--model", "gpt-4", "--system-prompt", "You are a helpful assistant"]


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