# ADR 001 Runtime 集成边界

日期：2026-09-14。上游版本：HelloAgents 1.0.0，commit `93e77ea60c13436636c9b39b6761ff8dfe940ba2`。
来源：https://github.com/jjyaoao/HelloAgents 。依赖采用精确 Git revision，完整依赖由 uv.lock 固定。

## 探针发现

- 实际入口是 `Tool`，并非 PRD 伪代码中的 BaseTool；执行接收 dict，返回 dataclass ToolResponse。
- 原生 ReadTool 把文件内容放在 data，默认执行路径只回传 text（读取行数），模型看不到正文。探针首次实跑暴露此问题；覆盖工具执行边界，把完整结构化结果序列化给模型。
- ReActAgent._build_messages 只生成 system + 本轮 user，未读取历史。必须在子类覆盖消息构建。
- 默认公开 Thought/Finish，违背六工具和不记录私有思维链的产品要求。覆盖 schema 和 builtin 集合，结束仍使用上游的无 tool_calls 文本分支。
- 上游会吞掉模型异常并输出“达到最大步数”，适配层需保留模型错误并报告真实失败类型。
- 同步循环没有逐条持久化钩子。以带 append 回调的消息列表记录 assistant/tool 事件；Controller 负责落盘，Adapter 不管理 Session 文件。
- 上游 ObservationTruncator 仅按行切分，max_bytes 只用于触发判断。DevFlow 在其结果上增加 UTF-8 字节边界，保证超长单行也受限。
- HistoryManager 接收 Message，直接压缩可能丢失 Function Calling 配对。通过 Adapter 将完整消息 JSON 编码成 Message，使用上游轮次管理；压缩边界保持完整轮次。
- SessionStore 为完整 JSON 快照，无树/逐事件日志。DevFlow 新建 append-only JSONL SessionManager，并保留上游快照导入入口，明确树和恢复由 DevFlow 实现。

## 决策

保留未修改的上游 ReActAgent.run 主循环，仅在 runtime/hello_agents_adapter.py 定义扩展钩子、工具包装、模型代理及上游 Context 组件桥接。关闭上游自动注册工具、Trace 和 Session，以防出现两套持久化状态。工具输入必须经过 Pydantic 严格校验，保留完整 JSON Schema；工具结果在边界映射为 ToolResponse，应用内部使用统一 ToolResult。

上游署名和许可见 THIRD_PARTY_NOTICES.md。此次实现不是复制上游源文件改名。
