**先定义这几个词**

1. `transcript`指一整个会话里保存下来的消息列表，也就是很多个 [Message](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py)。
2. `boundary marker`指由 [compact_boundary_message()](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py#L157) 生成的那条特殊消息。它本质上也是一条 `Message`，但它有两个特殊点：

   - `is_meta=True`
   - `metadata["subtype"] == "compact_boundary"`
3. `provider payload`指最终发给模型供应商的消息视图。当前项目里，这一步在 [QueryEngine._prepare_turn()](C:/Users/25901/Desktop/general-agent/src/engine/query_engine.py#L185) 里先做切片，再做 [normalize_messages_for_api()](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py#L175)。
4. `compact`
   指“把旧上下文压缩成更短的表达”。比如把前面 40 轮对话压成一段摘要，而不是原样全带上。


**1. 为什么需要 `compact_boundary_message`**

这个机制是为了解决一个非常实际的问题：

一个 Agent 会话越跑越长时，旧消息会不断堆积。旧消息堆积会带来 3 个问题：

1. 上下文越来越贵发给模型的输入越来越长，token 成本上升，延迟变大。
2. 上下文越来越脏很久以前的工具结果、旧计划、旧假设，可能已经过时了，但还在影响模型。
3. “压缩后又把原文带上”
   如果你已经把前 30 轮对话压成了一个摘要，但下一次请求时又把那 30 轮原文一起发给模型，那么压缩几乎白做了。

---

**2. 从 dataflow 的角度解释这个机制**

先看这条特殊消息是怎么定义的，在 [message_schema.py](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py#L157)：

- 输入：一个字符串 `reason`
- 输出：一条 `Message`
- 这条 `Message` 的关键元数据是：

```python
metadata={"subtype": "compact_boundary", "reason": reason}
```

然后在 [get_messages_after_compact_boundary()](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py#L167) 里，会从后往前扫描 `transcript`，找到最近的一条 boundary marker。
一旦找到，就只返回这条 marker 后面的消息。

最后在 [QueryEngine._prepare_turn()](C:/Users/25901/Desktop/general-agent/src/engine/query_engine.py#L185) 里，dataflow 是这样的：

1. `turn.messages`这是完整会话历史。
2. `compaction_manager.maybe_compact(turn.messages)`这里理论上可以返回“插入过 boundary 的消息列表”。
3. `get_messages_after_compact_boundary(compaction_result.messages)`这一步做“切片”。
4. `normalize_messages_for_api(...)`这一步做正规化，顺便把 boundary 自己过滤掉。
5. 得到 `turn.messages_for_query`
   这才是下一次真正发给模型的上下文。

我们用一个具体例子说清楚。

假设完整 `transcript` 是：

- 消息 1：用户问“分析银行板块”
- 消息 2：助手调用 `web_search`
- 消息 3：工具结果“银行板块偏稳”
- 消息 4：用户问“再看券商”
- 消息 5：工具结果“券商波动大”
- 消息 6：系统做了一次 compact，把前面的内容总结成一句摘要
- 消息 7：`compact_boundary_message("compacted turns 1-5")`
- 消息 8：摘要消息“历史摘要：银行稳，券商波动大”
- 消息 9：用户新问题“现在结合成交量继续判断”

如果没有 boundary：

- 下一次发给模型的，可能是消息 1 到消息 9 全部

如果有 boundary：

- [get_messages_after_compact_boundary()](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py#L167) 会返回消息 8 和消息 9
- boundary 自己会在 [normalize_messages_for_api()](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py#L175) 里被过滤掉
- 最终 provider payload 只包含：
  - 摘要
  - 当前问题

这就是这个机制的核心 dataflow。

---

**3. 这个机制是怎么解决问题的，真的解决了吗**

先说“理论上如何解决”。

它解决问题靠两步：

1. 用 `compact_boundary_message()` 在 `transcript` 里埋一个“切断点”
2. 用 `get_messages_after_compact_boundary()` 在构造本轮请求时只取切断点之后的消息

你接下来最值得追问的 4 个问题是：

1. compact 后的“摘要消息”应该放成 `assistant message`、`system message`，还是单独的 `meta message`？
2. 如果一个会话发生了多次 compact，为什么 [get_messages_after_compact_boundary()](C:/Users/25901/Desktop/general-agent/src/engine/message_schema.py#L167) 要“从后往前”找最近的一条 boundary？
3. boundary 机制和 `tool_result` 截断机制有什么区别？
4. 在你的 A 股 Agent 里，哪些内容应该被 compact，哪些内容绝对不能 compact？

如果你愿意，我下一条可以继续专门回答第 2 个问题：
**为什么 boundary 一定要是“最近一个边界生效”，而不是“所有边界都一起处理”。**
