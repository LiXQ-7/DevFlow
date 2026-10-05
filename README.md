# DevFlow 终端智能研发助手

基于 HelloAgents 1.0.0 的 Python 3.11 Coding Agent，提供代码检索、精确编辑、命令执行、上下文预算和可恢复树形会话。重点是可验证的工程能力，以及能追溯到 CSV 的评测结果。

## 快速启动

需要 Git 和 uv。首次安装会下载 Python 3.11 和锁定依赖。

```powershell
uv sync --frozen
Copy-Item .env.example .env
# 在本地 .env 填写 DEVFLOW_API_KEY、DEVFLOW_MODEL、DEVFLOW_BASE_URL
uv run devflow --new
```

本次工作区已有 `.venv`，可直接运行：

```powershell
.venv\Scripts\devflow.exe --new
.venv\Scripts\devflow.exe --prompt "读取 README.md，说明项目用途"
```

如果 uv 尚未加入 PATH，也可用 `python -m uv sync --frozen`。不能使用 Python 3.9 直接运行项目。
兼容 LLM_API_KEY / LLM_MODEL_ID / LLM_BASE_URL 和 OPENAI_API_KEY 等环境变量；环境变量优先于 .env。
仅配置支持 Function Calling 的模型。SDK HTTP 协议已通过本地兼容服务集成测试，并完成 DeepSeek Flash 官方 API 实测；其他模型需用自己的配置验证。DeepSeek 工具调用默认关闭思考模式，以适配当前 Runtime 的消息历史格式。

默认 Bash 需要显式开启：`uv run devflow --allow-shell`，或交互中输入 `/shell on`。
Windows 使用 PowerShell，Linux 使用 bash。文件工具限制在 project_root；命令策略有危险模式拦截、cwd 校验、超时和进程树终止，但不是操作系统沙箱。启用后只应在可信工程中运行。

## 已实现能力

| 模块 | 行为 |
|---|---|
| Read | UTF-8、默认 200 行/12 KB、行号、SHA256、mtime、续读位置 |
| Write | 显式覆盖策略、原子写入、保留已有文件权限 |
| Edit | 唯一精确替换、0 匹配 NOT_FOUND、多匹配 CONFLICT、hash/mtime 乐观锁 |
| Grep | ripgrep 优先、Python fallback、正则/字面搜索、排除构建目录、PARTIAL 和完整输出路径 |
| Bash | cwd 限制、默认 30 秒/最高 300 秒、stdout/stderr 落盘、退出码、超时清理 |
| TodoWrite | 结构化状态、唯一 ID、最多一个 in_progress，恢复及分支重建 |
| Context | 每次模型请求计入消息与工具 Schema、上游 TokenCounter、三种输出截断、结构化摘要 |
| Session | JSONL id/parent_id 树、fsync、尾部半行恢复、并发写入冲突检测、历史分支 |
| Skills / Trace | 四个按需工作流、模型/工具/上下文/Session 事件、关联 call_id、凭据脱敏 |

压缩摘要包含 Goal、Constraints、Done、InProgress、FailedAttempts、FilesRead、FilesModified、CurrentTODO、NextSteps。
采用确定性抽取，不增加摘要模型费用；保留用户要求原文。摘要与最新轮次仍超预算时明确失败，不悄悄删除约束。
完整历史不会被压缩删除。输出原文存放于项目 `.devflow/outputs/`，Trace 和 Session 也位于 `.devflow/`，已被 Git 忽略。

## 会话操作

```powershell
uv run devflow sessions
uv run devflow --resume SESSION_ID
uv run devflow --resume SESSION_ID tree
uv run devflow --resume SESSION_ID branch ENTRY_ID
uv run devflow --resume SESSION_ID compact
uv run devflow --resume SESSION_ID trace
uv run devflow --root D:/your/project --new --allow-shell
```

根命令选项必须放在子命令前。无参数默认恢复当前项目最近的会话。
交互命令：`/exit`、`/tree`、`/branch ID`、`/compact`、`/shell on`、`/shell off`。
分支只切换会话历史，不回滚工作区文件。恢复中遇到“调用已记入、结果未落盘”，会补充未知结果并要求核验真实状态，不自动执行原调用。系统不承诺副作用 exactly-once。

## 验证与评测

```powershell
uv run pytest
uv run python scripts/hello_agents_probe.py
uv run devflow bench tool
uv run devflow bench context
uv run devflow bench recovery
uv run devflow bench report
```

报告位于 `benchmark-results/<类型>-<模式>-<时间>/report.md`，伴随 CSV、元数据和原始证据。
本次已运行的精简证据也保存在 [docs/evidence](docs/evidence/report.md)，方便直接审阅。
2026-09-15 已完成 [DeepSeek 实测报告](docs/evidence/deepseek-live-20260915/report.md)：240 条单步工具选择严格匹配 226/240，合法输入子集 Schema 通过 200/200；12×20 轮 A/B 的累计输入下降 45.0%，其中包含 14 轮上下文预算中断，五点状态检查为 57/60。重复读取未改善。可直接使用的项目描述见 [简历版本](docs/resume-ready.md)。
240 条工具数据为 6×40，包括有意非法输入；12 组 Context 每组 20 轮；30 次故障为三类各 10 次。

**离线模式不测模型选择准确率或真实任务效果。** 工具模式执行标注参数；Context 模式使用固定轨迹验证预算机制，状态检查是上下文文本存在性；恢复模式使用真实退出的子进程和脚本模型。

配置模型后，显式运行真实评测（会产生 API 调用费用）：

```powershell
uv run devflow --allow-shell bench tool --live
uv run devflow --allow-shell bench context --live
```

Tool live 区分选择准确率、Schema 合法率和执行 SUCCESS 比例，并单列合法输入子集。Context live 记录每次 API usage、最终回答的五点字面检查、重叠 Read 计数和独立功能验收；A/B 工程初始状态相同。真实模型非确定性及简化任务影响外推性。
若 API 不提供 usage，则报告不可计算，不能把估算悄悄当作账单 Token。数据与指标口径见 [评测说明](docs/evaluation.md)。

本次付费实验使用 `scripts/run_live_evaluation.py`，有独立费用账本、并发调度和原始请求用量记录；上述通用 CLI live 命令不具备该费用上限。脚本参数见 `--help`，复现实验应使用新的输出目录。最终数据位于 `benchmark-results/deepseek-live-20260915-r2`，补测原因和保留规则记录在 `attempt-provenance.json`。本次余额减少约 9.14 元，评测结束时剩余 15.96 元。

## 项目阅读路线

1. [Runtime 适配决策](docs/ADR-001-runtime-integration.md)：实际 API 探针和上游缺口。
2. `devflow/tools/`：参数契约、路径策略、工具失败语义。
3. `devflow/controller.py` → `runtime/hello_agents_adapter.py`：事件钩子如何接入原生 ReAct 循环。
4. `devflow/context/` 和 `devflow/session/`：预算、完整轮次压缩、追加日志恢复。
5. `tests/`、`devflow/benchmarks/` 和 [演示指南](docs/demo.md)：如何复现、如何解释指标。

源码及依赖归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。当前进展与已验证限制见 [current_process.md](current_process.md)。
