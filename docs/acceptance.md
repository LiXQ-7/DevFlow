# PRD 验收映射

| 需求 | 实现入口 | 验证证据 |
|---|---|---|
| FR-01 CLI | devflow/cli.py | CliRunner、--help、sessions、wheel 构建 |
| FR-02 多步 Agent | runtime/hello_agents_adapter.py | 原生 ReAct、连续工具、历史、多调用、最大步数、模型异常测试 |
| FR-03/04 Read/Write | tools/coding.py | 行区间、中文、字节上限、覆盖策略、原子写、240 条语义回归 |
| FR-05 Edit | tools/coding.py | 0/1/多匹配、hash/mtime 冲突、CRLF 原样保留 |
| FR-06 Grep | tools/coding.py | rg/Python 双路径、字面/正则、PARTIAL、排除目录 |
| FR-07 Bash | tools/coding.py、safety.py | shell 开关、危险模式、cwd、stdout/stderr、超时和进程树 |
| FR-08 TODO | TodoWriteTool、session/tree.py | 唯一 ID、最多一个进行中、恢复快照 |
| FR-09/10 Context/Truncation | context/policy.py | 请求预算计入 schemas、超长单行/真实多行、完整输出落盘 |
| FR-11/12 Session/Tree | session/ | 分支保留兄弟节点、并发冲突、半行修复、完整坏行报错 |
| FR-13 Compaction | context/summary.py、session/tree.py | 九类状态摘要、完整轮次、持久化后重启还原、原历史不删除 |
| FR-14 Skills | skills/loader.py、builtin/ | 四文件按需加载、元数据展示和意图匹配 |
| FR-15 Trace | observability/trace.py、controller.py | 请求用量、call_id 配对、耗时、压缩、错误、脱敏 |
| FR-16 Benchmark | benchmarks/ | 240 工具、12×20 A/B、30 进程故障，CSV 汇总生成报告 |

模型兼容性已在本地 HTTP 服务上走通真实 SDK，并完成 DeepSeek Flash 官方 API 评测，详见 [实测报告](evidence/deepseek-live-20260915/report.md)。
现有 Windows 环境不允许创建符号链接，因此该项 OS 级测试跳过；路径越界等其余测试正常运行。
Linux CI 已配置但尚未在远端执行，不能声称跨平台全量验证通过。
独立 12307 业务源码未提供，业务场景 Demo 仅交付可执行步骤。

## 公开实验限制

- V1 没有 Docker/OS 沙箱；外部进程和非合作式并发修改不由文件工具提供完整隔离。
- 精确编辑不把 CRLF/LF 自动归一化，换行不一致会得到 NOT_FOUND，避免隐式修改整个文件。
- 提供的任务集是教学/工程回归数据，不能外推为 SWE-bench 或真实仓库总体完成率。
- 完整 Session/工具输出存储任务内容，不宜提交 Git；Trace 脱敏不等同于扫描任意源码中的全部秘密。
- 自动摘要保留用户约束和结构化工具状态，但 assistant 完成描述最多保留每条 1500 字符，本次真实模型最终回答五点字面检查为 57/60，不能外推为全面语义记忆正确率。

- A/B 累计输入下降 45.0%，包含 14 轮上下文预算中断；重复 Read 从 112 增至 121，不能声称重复读取改善或相同执行量下的纯压缩收益。
