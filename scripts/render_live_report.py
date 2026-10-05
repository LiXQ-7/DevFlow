"""Build reviewable evidence and a resume excerpt from the completed paid evaluation."""

import json
import shutil
from pathlib import Path

from run_live_evaluation import save_balance, summarize

from devflow.benchmarks.common import write_csv
from devflow.config import Config


def main():
    source = Path("benchmark-results/deepseek-live-20260915-r2")
    metrics = summarize(source)
    after = save_balance(Config.load(), source, "balance-after.json")
    destination = Path("docs/evidence/deepseek-live-20260915")
    destination.mkdir(parents=True, exist_ok=True)
    tool_results = [
        json.loads(p.read_text(encoding="utf-8")) for p in (source / "tool-results").glob("*.json")
    ]
    failures = [r for r in tool_results if not r["selection_correct"]]
    write_csv(destination / "tool_selection_failures.csv", failures)
    for name in (
        "tool_calling.csv",
        "context_ab.csv",
        "state_scores.csv",
        "metrics.json",
        "protocol.json",
        "attempt-provenance.json",
        "budget.json",
        "balance-before.json",
        "balance-after.json",
    ):
        shutil.copyfile(source / name, destination / name)
    a, b = metrics["context_input_tokens"]["A"], metrics["context_input_tokens"]["B"]
    valid = metrics["context_rows"] == 480 and metrics["context_all_usage_present"]
    statuses = metrics["context_turn_statuses"]
    valid = valid and not any(statuses.get(s, 0) for s in ("BudgetExceeded", "PermissionError"))
    savings = (a - b) / a if a and valid else None
    score_a, score_b = metrics["A"], metrics["B"]
    retention = score_b["retained"] / score_b["state_points"] if score_b["state_points"] else 0
    repeated = (
        (score_a["repeated_reads"] - score_b["repeated_reads"]) / score_a["repeated_reads"]
        if score_a["repeated_reads"]
        else None
    )
    selection = metrics["tool_correct"] / metrics["tool_cases"]
    expense = 25.10 - after
    totals = {
        **metrics,
        "token_saving": savings,
        "state_retention_literal": retention,
        "repeated_read_reduction": repeated,
        "balance_decrease_cny": round(expense, 2),
        "remaining_balance_cny": after,
        "primary_context_valid": valid,
    }
    (destination / "resume_metrics.json").write_text(
        json.dumps(totals, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cost_text = (
        f"余额由 25.10 元降至 {after:.2f} 元，变化约 {expense:.2f} 元（包含联通测试和被中断实验）。"
    )
    text = f"""# DeepSeek 真实模型评测

模型：deepseek-flash；非思考模式；temperature=0；评测日期 2026-09-15。真实调用官方 API，通过生产 Runtime 和六类 Coding Tools 的 Schema。

{cost_text}

## 工具选择与参数

- 固定 240 条单步工具选择用例，匹配 {metrics["tool_correct"]}/{metrics["tool_cases"]}，严格工具名称匹配率 **{selection:.2%}**；接口错误 {metrics["tool_errors"]}。
- 其中 200 条输入参数本身合法的用例，模型输出 Schema 通过 {metrics["normal_schema_pass"]}/200。
- 另 40 条刻意非法输入单列，不把正确拒绝和模型参数合法混为同一指标。工具执行能力另有既有 240 条离线语义回归，本实验没有执行模型生成的命令。
- 14 条工具选择偏差均发生在 Edit：部分先 Read/Grep 再修改，部分使用 Write 整体替换。部分为合理替代路线，但仍按预先固定的单步标签计为不匹配，未事后调高分数。

## Context A/B

- 12 个固定工程任务，每组 20 个用户轮次，每组分别运行 A/B，共 {metrics["context_rows"]} 行轮次记录。
- A 禁用历史压缩/输出截断并扩大默认 Read；B 使用 16000 Token 窗口、1024 预留、4096 字节/100 行输出限制和结构化压缩。每轮最多 5 次模型调用；输出上限 768 Token；无模型摘要调用。
- 累计输入以每次 API usage 聚合：A={a:,}，B={b:,}；节省 **{f"{savings:.2%}" if savings is not None else "未形成有效完整比较"}**。
- 最终回答预埋状态字面命中：A={score_a["retained"]}/{score_a["state_points"]}，B={score_b["retained"]}/{score_b["state_points"]}（B **{retention:.2%}**）。检查验收标记、函数名、依赖约束、代码文件和测试文件，不能外推为任意语义记忆正确率。
- 独立功能断言通过：A={score_a["completed"]}/{score_a["tasks"]}，B={score_b["completed"]}/{score_b["tasks"]}。包含正数、负数与零值，不相信模型自述。
- 重复 Read：A={score_a["repeated_reads"]}，B={score_b["repeated_reads"]}，下降率 {f"{repeated:.2%}" if repeated is not None else "N/A"}。无论是否改善均保留原始结果。
- 轮次状态：{json.dumps(statuses, ensure_ascii=False)}。max_steps 表示该轮达到 5 次调用上限，并不等于整个任务失败；上下文预算中断保留在统计中。

## 实验过程和限制

首次调度器初始化失败发生于发出请求前，原始记录在 deepseek-live-20260915。首次正式运行 r1 完成所有工具评测；Context 因将缓存输入按未命中价格估算而提前触发费用保护，另有一次 Windows 费用账本替换冲突。
补测 r2 仅修复费用核算和账本重试，模型、任务、工具和上下文设置保持不变。保留所有 240 条原始工具结果；保留原本完成且未发生费用账本故障的 context-01/context-02 两组；其余组从相同初始工程重新运行，原始失败尝试全部保留。保留规则按基础设施状态制定，不按任务分数筛选。

任务为模板生成的 12 个小型计算函数修复工程并包含长构建日志，结论仅适用于该测试集，不代表 SWE-bench 或复杂真实业务仓库成功率。Token 下降是请求输入量变化，包含 14 轮上下文预算中断，不代表同等执行量下的纯压缩收益，也不等同于缓存计费后的账单同比下降。

价格参考：https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ 。预算按 Flash 高峰价格保守估算（未命中输入 2 元、命中输入 0.04 元、输出 8 元 / 百万 Token），实际余额核对为准。
完整会话、最终回答和独立验收输出在 benchmark-results/deepseek-live-20260915-r2/workspaces；前两组证据复制自 r1。
"""
    (destination / "report.md").write_text(text, encoding="utf-8")
    context_bullet = (
        f"在 12 组 × 20 轮日志密集型会话 A/B 测试中，预算策略下累计输入 Token 降低 {savings:.1%}，预埋关键状态保留 {score_b['retained']}/{score_b['state_points']}。"
        if valid
        else "已实现分段读取、输出截断与结构化历史压缩，真实 A/B 结果详见评测报告。"
    )
    resume = f"""# DevFlow 简历描述

**DevFlow | 终端智能研发助手 | Agent 开发**

**技术栈：** Python 3.11、OpenAI Compatible API、Function Calling、Pydantic、tiktoken、Typer

**项目简介：** 基于开源 Agent Runtime 二次开发本地终端 Coding Agent，支持代码检索、文件编辑、命令执行与测试反馈，围绕工具调用可靠性、长上下文成本与任务中断恢复进行工程化设计。

- 基于 ReAct 与 Function Calling 扩展 Agent 执行链路，构建 Read、Write、Edit、Grep、Bash、TodoWrite 六类核心工具；结合 Pydantic 校验、哈希乐观锁及原子写入处理非法参数与编辑冲突。在 DeepSeek Flash 的 240 条单步工具选择评测中，严格匹配率 {selection:.1%}，合法输入子集 Schema 校验通过 {metrics["normal_schema_pass"]}/200。
- 基于 TokenCounter、HistoryManager 与 ObservationTruncator 设计分段读取、输出截断及结构化历史压缩，保留最近完整轮次、任务约束、文件状态和 TODO；{context_bullet}
- 设计 JSONL Session Tree，通过 id / parent_id、追加写入和 fsync 支持会话恢复与历史分支；完成 30 次故障注入验证，识别 10 次副作用结果未知状态，避免恢复时自动重放原调用。
- 将代码审查、异常排查、单元测试生成和 Git 提交规范沉淀为四类按需 Skills，结合 TodoWrite 持久化任务进度，通过 TraceLogger 关联工具调用与结果，记录模型用量、执行耗时和错误事件。

面试口径：240 条是预设单步工具匹配，不是复杂任务成功率；200 条为参数本身合法的子集；状态保留是五点字面检查；30 次故障实验使用模型替身和真实子进程退出。45.0% 的输入下降包含 14 轮上下文预算中断，不代表同等执行量下的纯压缩收益；重复 Read 实际增加 8.04%，不写下降。项目时间填写实际参与周期。详见 [完整评测报告](evidence/deepseek-live-20260915/report.md)。
"""
    (Path("docs") / "resume-ready.md").write_text(resume, encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False))


if __name__ == "__main__":
    main()
