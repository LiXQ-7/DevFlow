# 上游与实现归属

DevFlow 使用 [HelloAgents](https://github.com/jjyaoao/HelloAgents) 作为外部 Python Runtime，
固定版本 1.0.0，commit `93e77ea60c13436636c9b39b6761ff8dfe940ba2`。
上游作者：HelloAgents Team / jjyaoao 及贡献者。上游 LICENSE 标注 CC BY-NC-SA 4.0。
上游许可原文随依赖分发，参考 [上游 LICENSE](https://github.com/jjyaoao/HelloAgents/blob/93e77ea60c13436636c9b39b6761ff8dfe940ba2/LICENSE)。

保留并调用上游 ReActAgent 主循环、ToolRegistry、ToolResponse、TokenCounter、HistoryManager、
ObservationTruncator；没有修改上游安装包或把源码复制改名。适配与 API 差异记录见 docs/ADR-001-runtime-integration.md。

DevFlow 的主要实现：六工具的 Pydantic 约束及执行策略、Runtime 的历史/事件钩子、
CodingSummary/预算策略、JSONL Session Tree/不确定结果恢复、CLI、评测数据与脚本。
SessionStore 的现有完整快照 API 与新增树日志的关系在 ADR 中明确区分。

[Pi Coding Agent](https://github.com/earendil-works/pi) 为终端交互、树形会话与按需 Skills 的设计参考，未引入其 Runtime 或复制源码。
本仓库定位学习与秋招演示项目，不对所有第三方依赖作统一许可声明。
