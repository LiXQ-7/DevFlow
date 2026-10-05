"""Generate resume-ready facts strictly from saved CSVs, never target constants."""

import csv
import json
from pathlib import Path


def latest(directory, prefix):
    matches = sorted(path for path in directory.glob(prefix + "-*") if path.is_dir())
    return matches[-1] if matches else None


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def run(directory: Path):
    text = "# DevFlow 可验证简历事实\n\n以下由保存的 CSV 计算。离线结果不替代真实模型评测。\n\n"
    facts = {}
    tool = latest(directory, "tool-live")
    if tool:
        data = rows(tool / "tool_calling.csv")
        total = len(data)
        facts["tool_selection_accuracy"] = sum(int(r["selection_correct"]) for r in data) / total
        facts["schema_pass_rate"] = sum(int(r["schema_valid"]) for r in data) / total
        text += f"- 真实模型 {total} 条工具评测：选择准确率 {facts['tool_selection_accuracy']:.2%}，全量 Schema 通过率 {facts['schema_pass_rate']:.2%}；含负例，需同时引用子集说明。\n"
    else:
        text += "- 六类 Coding Tools；已提供 240 条回归数据。真实模型工具选择/Schema 指标：未测。\n"
    context = latest(directory, "context-live")
    if context:
        data = rows(context / "context_ab.csv")
        if all(row["input_tokens"] for row in data):
            totals = {
                arm: sum(int(r["input_tokens"]) for r in data if r["arm"] == arm)
                for arm in ("A", "B")
            }
            facts["token_saving"] = (
                (totals["A"] - totals["B"]) / totals["A"] if totals["A"] else None
            )
            text += f"- 真实模型 Context 累计输入 Token：A={totals['A']}，B={totals['B']}。\n"
        else:
            text += "- Context live 存在缺失 usage，Token 节省不可计算。\n"
        scores = rows(context / "state_scores.csv")
        b = [r for r in scores if r["arm"] == "B"]
        facts["state_retention_literal"] = sum(int(r["retained"]) for r in b) / sum(
            int(r["state_points"]) for r in b
        )
    else:
        text += "- 已提供 12 组 × 20 轮 A/B 框架。真实模型 Token 节省、最终回答状态保留与任务完成率：未测。\n"
    recovery = latest(directory, "recovery-process")
    if recovery:
        data = rows(recovery / "fault_injection.csv")
        success = sum(int(row["successful_resume"]) for row in data)
        unknown = sum(int(row["uncertain_side_effect"]) for row in data)
        facts["consistent_resume_rate"] = success / len(data)
        text += f"- {len(data)} 次进程级故障：{success} 次恢复并继续（{success / len(data):.2%}）；{unknown} 次副作用结果不确定且未自动重放。模型使用离线替身。\n"
    text += "- 四类按需 Skills、TodoWrite 与 TraceLogger 已实现。\n\n不应沿用原简历的模拟百分比；应同时记录模型、数据集版本和实验口径。\n"
    (directory / "resume_metrics.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    path = directory / "report.md"
    path.write_text(text, encoding="utf-8")
    return path
