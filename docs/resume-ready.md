# DevFlow 简历描述

**DevFlow | 终端智能研发助手 | Agent 开发**

**技术栈：** Python 3.11、OpenAI Compatible API、Function Calling、Pydantic、tiktoken、Typer

**项目简介：** 基于开源 Agent Runtime 二次开发本地终端 Coding Agent，支持代码检索、文件编辑、命令执行与测试反馈，围绕工具调用可靠性、长上下文成本与任务中断恢复进行工程化设计。

- 基于 ReAct 与 Function Calling 扩展 Agent 执行链路，构建 Read、Write、Edit、Grep、Bash、TodoWrite 六类核心工具；结合 Pydantic 校验、哈希乐观锁及原子写入处理非法参数与编辑冲突。在 DeepSeek Flash 的 240 条单步工具选择评测中，严格匹配率 94.2%，合法输入子集 Schema 校验通过 200/200。
- 基于 TokenCounter、HistoryManager 与 ObservationTruncator 设计分段读取、输出截断及结构化历史压缩，保留最近完整轮次、任务约束、文件状态和 TODO；在 12 组 × 20 轮日志密集型会话 A/B 测试中，预算策略下累计输入 Token 降低 45.0%，预埋关键状态保留 57/60。
- 设计 JSONL Session Tree，通过 id / parent_id、追加写入和 fsync 支持会话恢复与历史分支；完成 30 次故障注入验证，识别 10 次副作用结果未知状态，避免恢复时自动重放原调用。
- 将代码审查、异常排查、单元测试生成和 Git 提交规范沉淀为四类按需 Skills，结合 TodoWrite 持久化任务进度，通过 TraceLogger 关联工具调用与结果，记录模型用量、执行耗时和错误事件。

面试口径：240 条是预设单步工具匹配，不是复杂任务成功率；200 条为参数本身合法的子集；状态保留是五点字面检查；30 次故障实验使用模型替身和真实子进程退出。45.0% 的输入下降包含 14 轮上下文预算中断，不代表同等执行量下的纯压缩收益；重复 Read 实际增加 8.04%，不写下降。项目时间填写实际参与周期。详见 [完整评测报告](evidence/deepseek-live-20260915/report.md)。
