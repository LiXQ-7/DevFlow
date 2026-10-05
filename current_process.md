# DevFlow 当前进展

最后同步：2026-10-05。阶段：V1 已完成本地验收、DeepSeek 真实模型评测、简历交付，并发布至公开 GitHub 仓库。

## 项目目的

基于 HelloAgents 的终端 Coding Agent，围绕工具调用稳定性、上下文控制与可恢复会话提供可运行实现和可复现证据。

## 已确认决策

- 需求依据：根目录 DevFlow_PRD_AI_Coding实施方案_V1.0.docx 和用户提供的简历功能范围。
- Python 3.11，HelloAgents 1.0.0 固定 commit `93e77ea60c13436636c9b39b6761ff8dfe940ba2`，uv.lock 固定依赖；上游源码未修改。
- 保留上游 ReAct 主循环，只在适配层扩展消息、六工具 Schema、结构化响应、逐请求预算和异常可见性。
- 单 Agent；无 IDE/Web/MCP/多 Agent。Bash 显式启用，Windows PowerShell / Unix bash，非 OS 沙箱。
- Session 位于项目 .devflow，采用 append/fsync JSONL 树；会话分支不回滚文件；结果未知不自动重放。
- 摘要采用确定性抽取。模拟目标百分比不用于实测报告；离线模式与真实模型模式明确区分。
- 简历用“基于开源 Agent Runtime 二次开发”，源码及归属文档保留实际上游信息。DeepSeek Flash 官方 API 使用非思考模式、temperature=0；凭据仅在被 Git 忽略的本地配置中。
- GitHub 远端为公开仓库 `LiXQ-7/DevFlow`，默认分支 `main`；真实 `.env`、`.devflow`、原始 benchmark 工作区、虚拟环境和构建产物不得提交。

## 已完成

- `devflow/tools/`：Read/Write/Edit/Grep/Bash/TodoWrite，Pydantic 严格 Schema、路径检查、原子写和精确匹配、rg/Python 搜索、命令超时、完整输出留存。
- `devflow/runtime/hello_agents_adapter.py`：上游唯一生产耦合层，真实 HTTP 兼容 API、多步执行、工具配对和 usage 统计。
- `devflow/context/`：计入工具 Schema 的缓存 Token 估算、按真实行数及字节截断、九类结构化摘要、完整轮次压缩。
- `devflow/session/`：持久化树、恢复、分支、TODO 恢复、尾部半行修复、完整损坏记录拒绝、并发写冲突检测。
- `devflow/skills/builtin/`：debug/code-review/unit-test/git-commit 四工作流；Trace 按 call_id 关联并脱敏。
- `devflow/cli.py`：多轮交互、单轮 prompt、sessions/tree/branch/compact/trace 和四个 bench 子命令。
- `devflow/benchmarks/data/`：240 条工具输入、12 组 20 轮任务、30 条故障；CSV/metadata/report 和从 CSV 生成的简历事实。
- `docs/`：API 探针、ADR、验收矩阵、评测口径、演示指南、精简实测证据；README 和第三方归属说明。
- 可安装 wheel：`dist/devflow_agent-0.1.0-py3-none-any.whl`，包含四 Skills 和三套数据；已配置 Windows/Linux CI，尚未远端执行。
- `devflow/benchmarks/paid.py`、`scripts/run_live_evaluation.py`：并发实测、缓存命中计费、费用预留、完整 usage 捕获、Windows 账本原子替换重试；未知请求失败按预留上限计费。
- `docs/evidence/deepseek-live-20260915/`：实测 CSV、指标、固定协议、补测溯源及报告；`docs/resume-ready.md`：对应真实结果的简历及面试口径。
- 当前仓库未包含此前记录的 `docs/DevFlow-面试知识库说明.md`；面试准备以 `docs/resume-ready.md`、评测报告和源码为准，后续如需该文档应重新生成并校验后提交。
- 已创建并推送公开 GitHub 仓库 `https://github.com/LiXQ-7/DevFlow`；初始提交为 `b9f8554`。`.gitignore` 额外排除 `.idea/` 与 `*.iml`。

## 在进行 / 阻塞

本次授权的付费评测已结束，无待运行付费任务。余额由 25.10 元降至 15.96 元，变化约 9.14 元，包含联通测试及中断尝试。不存在待用户确认的交付阻塞。
完整原始记录在 `benchmark-results/deepseek-live-20260915-r2`。首次调度初始化失败、r1 费用保守误判和一次 Windows 账本替换故障均保留；r2 沿用全部 240 条工具结果及两组无基础设施故障的 Context，另外十组按同一协议重跑，未按得分选样。
12307 项目源码未提供，其业务场景仅有演示步骤，没有运行证据。

## 验证记录

- `.venv/Scripts/python scripts/hello_agents_probe.py`：通过；首次探针暴露上游 Read 内容丢失问题，适配修正记录在 ADR。
- `.venv/Scripts/python -m pytest -q`：全套测试通过（45 passed, 1 skipped）；跳过项为当前 Windows 不授予符号链接创建权限。
- 2026-09-23 重新执行 `.venv/Scripts/python -m pytest -q`：全套测试仍为通过状态（输出 45 个通过标记、1 个平台跳过标记）；执行 `.venv/Scripts/ruff.exe check devflow tests scripts` 和 `ruff format --check`：通过，46 个 Python 文件格式一致。
- 2026-10-05 仓库核对确认 `docs/DevFlow-面试知识库说明.md` 当前缺失，已移除将其视为现有交付物的过期记录。
- 2026-10-05 改为公开仓库前扫描全部 Git 历史，未发现真实 `.env`、API Key 或 Bearer Token；需求文档中未检测到邮箱、手机号或凭据，GitHub 可见性已核验为 PUBLIC。
- 本地 HTTP 集成：真实 SDK → HelloAgents → Write → 工具结果回传 → 最终回答及 API usage，测试通过；外部 DeepSeek 结果单独记录如下。
- `.venv/Scripts/ruff check devflow tests scripts`、`ruff format --check`：通过，46 个 Python 文件格式一致。
- `python -m uv lock --check`：通过；`.venv/Scripts/python -m build --wheel`：构建成功。
- `devflow bench tool`：最新离线语义符合 **240/240**，包括预期拒绝；不是模型选择准确率。
- `devflow bench context`：完整 12×20×2 回放已完成；估算输入 A=112279272、B=2991048；97.34% 仅为固定大日志轨迹的估算节省，不能写作真实模型收益。状态文本包含率 100%，重复 Read A/B 各 228（下降 0%），任务完成率未测。
- `devflow bench recovery`：真实子进程故障 **30/30** 恢复并继续；10 次副作用未知且未重放。包含 Write、Bash 和命令超时后退出，5 次尾部半行。
- 初次工具回归 236/240 的原因是测试夹具写入 CRLF、参数为 LF；修正夹具固定换行，并新增 CRLF 原样保留回归。旧原始运行保存在 benchmark-results。
- `scripts/export_evidence.py`：最新 CSV/报告复制到 docs/evidence；完整原始工具输出/日志留在被 Git 忽略的 benchmark-results。
- DeepSeek 工具单步选择：226/240（94.2%），合法输入 Schema 200/200；40 条故意非法输入单列。14 个选择偏差均在 Edit，严格按原始标签计分。
- DeepSeek Context：12×20×2 共 480 轮记录，API 输入 A=9,314,858、B=5,120,803，预算策略下下降 45.0%；最终状态字面检查 A=60/60、B=57/60；独立功能验收两组均 12/12。
- Context 状态：completed 410、max_steps 56、ContextBudgetExceeded 14，全部保留。尚未发送请求即触发预算保护的轮次记 0 API Token，有请求但 usage 未知则不能按 0 处理；有针对性回归测试。
- 重复 Read A=112、B=121，增加 8.04%，简历已移除原下降描述。30 次故障恢复仍为先前脚本模型加真实进程退出实验，不混作在线模型结果。

## 后续步骤

1. 面试准备优先使用 `docs/resume-ready.md` 和 `docs/evidence/deepseek-live-20260915/report.md`；回答量化问题时继续对照分母、失败样例和 A/B 口径。本次无需继续消耗 API。
2. 后续改进方向：减少重复 Read、改善最近轮次超预算处理；另立实验比较同等执行量下收益。
3. 提供真实 12307 目录后按 docs/demo.md 演示；在 Linux CI 环境补齐平台验证。这些为未来工作，不影响当前交付。

## 风险与未验证边界

- 不承诺 exactly-once、文件系统断电级一致性、操作系统沙箱或对恶意外部并发写入完全隔离。
- 工作区内 Session/完整输出包含任务内容；Trace 脱敏不代表源码秘密的全面扫描。
- Context 任务是工程教学集，最终回答五点字面规则不等同于全面语义正确率。
- 45.0% 包含 14 轮上下文预算中断，不能声称同等执行量下纯压缩收益或账单同比节省。基线扩大 Read 且关闭截断，收益是组合策略效果，不能归因于单个压缩组件。
- 完整约束加最近轮次超预算会显式失败；不会为降低 Token 悄悄删除要求。
- GitHub 当前为公开仓库；后续每次提交仍需避免加入凭据、个人信息和本地运行产物，密钥如曾误提交必须立即轮换并清理历史。

## 接手入口

先读 README.md → docs/ADR-001-runtime-integration.md → docs/acceptance.md → docs/evidence/deepseek-live-20260915/report.md → docs/resume-ready.md。
功能协调入口 controller.py；上游变更先重新运行探针。修改后跑相关 pytest，再同步本文件；不得把未运行的 live 指标填成已测。
