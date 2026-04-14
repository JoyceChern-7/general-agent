**workflow**

可以把 **load_settings(options, cwd)** 理解为下面这条流程：

1. 输入 **options** 和 **cwd**
2. 读取 **.general-agent/settings.json**
3. 读取环境变量快照 **EnvSettings**
4. 决定 **session_dir**
5. 决定 **api_key**
6. 决定 **base_url**
7. 决定 **api_timeout_ms**
8. 构造 **RuntimeSettings**
9. 构造 **ModelSettings**
10. 决定 **tushare_token**
11. 构造 **ToolSettings**
12. 返回 **AppSettings**

---

**dataflow:**
把数据流写成箭头，会更清楚：

**CLIOptions(由cli.py通过用户输入的命令构造) + cwd(当前工作目录) + os.environ(系统环境变量) + settings.json(.general-agent\settings.json)
-> **_load_json_settings(cwd)** 得到 **JsonSettings**
-> **EnvSettings()** 得到 **EnvSettings**
-> **_first_value/_env_value/_json_env** 决定中间值
-> 构造 **RuntimeSettings**
-> 构造 **ModelSettings**
-> 构造 **ToolSettings**
-> 封装成 **AppSettings**
-> 返回给 **main.build_runtime()****

---

最重要的是优先级的处理:
对于同个字段来说, 我们规定 cli ( `cli.py` 通过启动时的命令构造的) > general-agent\settings.json 里配置的 > 默认值.

也就是说, 如果我们启动 cli时没有传入相关字段的值, 那么就用 settings.json 里的配置的参数, 如果都没有, 就用默认值.
