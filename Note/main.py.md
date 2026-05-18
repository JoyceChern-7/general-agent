main:

之前 cli 构造了一个 CLIOptions, 里面大概就是一些启动 cli 时需要的一些字段, 最后 cli 把这些东西传入 main.run

关于 main 的流程

首先是做了一些胶水工作, 比如 _resolve_cwd 就是恢复路径.

启动各种组件: queryEngine, tool_registry, compaction_manager, token_budget. 其中最重要的就是 queryEngine

然后把这些组件打包成一个 AppRuntime 对象, 如果是交互模式就把 runtime 传给 run_repl, 启动整个交互界面.

然后 run_repl, 又会不断地跑 queryEngine.
