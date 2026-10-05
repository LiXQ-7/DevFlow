"""Offline replay validates cost mechanics; live mode measures actual model trajectories."""

import json
import subprocess
import sys

from devflow.context.policy import CodingContextPolicy
from devflow.controller import DevFlowController
from devflow.tools.base import ToolResult

from .common import load_data, metadata, report_dir, write_csv, write_report


def fixture(root, task):
    root.mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    (root / "calculator.py").write_text(
        f"def {task['function']}(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (root / "tests/test_calculator.py").write_text(
        f"from calculator import {task['function']}\n\ndef test_add():\n    assert {task['function']}(2, 3) == 5\n",
        encoding="utf-8",
    )
    (root / "logs/build.log").write_text(
        "".join(f"build step {i}: module checked\n" for i in range(5000))
        + "FAILED tests/test_calculator.py: expected 5, got -1\n",
        encoding="utf-8",
    )


def repeat_reads(events):
    seen, repeated = [], 0
    for event in events:
        if event.get("event") != "tool_call" or event.get("tool_name") != "Read":
            continue
        args = event.get("args_redacted", {})
        if not isinstance(args, dict):
            continue
        path, start, end = args.get("path"), args.get("start_line", 1), args.get("end_line")
        end = end or start + 199
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        repeated += int(any(p == path and s <= end and start <= e for p, s, e in seen))
        seen.append((path, start, end))
    return repeated


def request_usage(requests, status):
    """A context-policy rejection before any request costs zero, not unknown API usage."""
    if not requests and status == "ContextBudgetExceeded":
        return 0, "no_request_context_guard"
    if requests and all(r.get("input_tokens") is not None for r in requests):
        return sum(r["input_tokens"] for r in requests), "api_usage"
    return "", "unavailable"


def offline_task(cfg, task, root, arm):
    fixture(root, task)
    local = cfg.model_copy(update={"project_root": root})
    policy = CodingContextPolicy(local)
    messages, rows = [], []
    log = (root / "logs/build.log").read_text(encoding="utf-8")
    for turn, prompt in enumerate(task["prompts"], 1):
        messages.append({"role": "user", "content": prompt})
        before = policy.count(messages)
        if arm == "B":
            messages, _ = policy.compact(messages)
        tokens = policy.count(messages)
        rows.append(
            {
                "task": task["id"],
                "arm": arm,
                "turn": turn,
                "input_tokens": tokens,
                "tokens_before_policy": before,
                "token_source": "local_estimate",
                "summary_input_tokens": 0,
                "status": "offline_replay",
            }
        )
        call_id = f"read-{turn}"
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "Read",
                            "arguments": '{"path":"logs/build.log","start_line":1,"end_line":5001}',
                        },
                    }
                ],
            }
        )
        result = ToolResult(
            text=log,
            data={
                "path": "logs/build.log",
                "sha256": "fixture-v1",
                "start_line": 1,
                "end_line": 5001,
            },
        )
        if arm == "B":
            result = policy.truncate("Read", result)
        messages.append(
            {"role": "tool", "tool_call_id": call_id, "content": result.model_dump_json()}
        )
        messages.append(
            {
                "role": "assistant",
                "content": "Observed build failure; no model inference in replay.",
            }
        )
    encoded = json.dumps(messages, ensure_ascii=False)
    retained = sum(point in encoded for point in task["state_points"])
    # Same scripted actions in both arms: no invented repeated-read reduction or task success.
    return rows, {
        "task": task["id"],
        "arm": arm,
        "retained": retained,
        "state_points": len(task["state_points"]),
        "repeated_reads": 19,
        "completion": "unmeasured",
        "state_source": "serialized_context_presence",
    }


def live_task(cfg, task, root, arm):
    fixture(root, task)
    local = cfg.model_copy(update={"project_root": root})
    controller = DevFlowController(local, new=True)
    if arm == "A":
        controller.prepare = lambda messages, schemas: messages
        controller.execute = lambda name, args: (
            controller.tools[name].execute(args)
            if name in controller.tools
            else ToolResult.error("UNKNOWN_TOOL", name)
        )
        controller.tools["Read"].default_lines = 5001
        # Baseline explicitly disables all three optimizations, including default Read byte budget.
        original = controller.tools["Read"].execute
        controller.tools["Read"].execute = lambda args: original({"max_bytes": 1_000_000, **args})
    rows, final = [], ""
    for turn, prompt in enumerate(task["prompts"], 1):
        before = len(controller.trace.records())
        status = "completed"
        try:
            result = controller.run_turn(prompt)
            final, status = result.text, result.status
        except Exception as exc:
            status = type(exc).__name__
        requests = [r for r in controller.trace.records()[before:] if r["event"] == "llm_request"]
        input_tokens, token_source = request_usage(requests, status)
        rows.append(
            {
                "task": task["id"],
                "arm": arm,
                "turn": turn,
                "input_tokens": input_tokens,
                "estimated_input_tokens": sum(r["estimated_input_tokens"] for r in requests),
                "token_source": token_source,
                "summary_input_tokens": 0,
                "status": status,
            }
        )
    code = (
        f"from calculator import {task['function']} as f; "
        "assert f(2,3)==5; assert f(0,0)==0; assert f(-2,3)==1; assert f(-2,-3)==-5"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=root, capture_output=True, timeout=15
        )
        complete = int(result.returncode == 0)
        (root / "acceptance.txt").write_bytes(result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        complete = 0
    (root / "final_answer.txt").write_text(final, encoding="utf-8")
    return rows, {
        "task": task["id"],
        "arm": arm,
        "retained": sum(point in final for point in task["state_points"]),
        "state_points": len(task["state_points"]),
        "repeated_reads": repeat_reads(controller.trace.records()),
        "completion": complete,
        "state_source": "final_answer_literal_rubric",
    }


def run(cfg, output, live=False):
    if live and not cfg.api_key.get_secret_value():
        raise ValueError("Configure API credentials before live Context A/B")
    if live and not cfg.allow_shell:
        raise ValueError("Live task evaluation runs generated code; use --allow-shell explicitly")
    directory = report_dir(output, "context", "live" if live else "offline")
    rows, scores = [], []
    for task in load_data("context_tasks.jsonl"):
        for arm in ("A", "B"):
            root = (directory / "workspaces" / task["id"] / arm).resolve()
            values, score = (live_task if live else offline_task)(cfg, task, root, arm)
            rows.extend(values)
            scores.append(score)
    write_csv(directory / "context_ab.csv", rows)
    write_csv(directory / "state_scores.csv", scores)
    totals = {
        arm: sum(
            row["input_tokens"]
            for row in rows
            if row["arm"] == arm and isinstance(row["input_tokens"], int)
        )
        for arm in ("A", "B")
    }
    complete_usage = all(isinstance(row["input_tokens"], int) for row in rows)
    savings = (totals["A"] - totals["B"]) / totals["A"] if totals["A"] and complete_usage else None
    b = [row for row in scores if row["arm"] == "B"]
    retention = sum(row["retained"] for row in b) / sum(row["state_points"] for row in b)
    repeats = {
        arm: sum(row["repeated_reads"] for row in scores if row["arm"] == arm) for arm in ("A", "B")
    }
    reduction = (repeats["A"] - repeats["B"]) / repeats["A"] if repeats["A"] else None
    metadata(
        directory,
        cfg,
        "context_tasks.jsonl",
        mode="live" if live else "offline_replay",
        groups=12,
        rounds=20,
        arms=2,
        summary_strategy="deterministic_extractive",
        state_rubric="literal five point rubric, not semantic judge",
        note="Offline state is context presence; live state is final answer. Offline task completion is unmeasured.",
    )
    saving_text = f"{savings:.2%}" if savings is not None else "不可计算（缺失 API usage）"
    text = f"# Context A/B\n\n模式：{'真实模型' if live else '离线固定轨迹回放'}；12 组 × 20 轮 × A/B。\n\n"
    text += f"累计输入 Token：A={totals['A']}，B={totals['B']}；节省 {saving_text}。来源：{'API usage' if live else '本地估算，不可作为真实模型成本收益'}。摘要为确定性抽取，无额外模型调用。\n\n"
    text += f"B 状态检查：{retention:.2%}（{'最终回答字面命中' if live else '上下文包含状态，不代表模型记住或任务成功'}）。\n\n"
    text += f"重复读取：A={repeats['A']}，B={repeats['B']}；下降 {f'{reduction:.2%}' if reduction is not None else 'N/A'}。\n\n"
    if live:
        text += (
            "任务验收："
            + "；".join(
                f"{arm}={sum(int(r['completion']) for r in scores if r['arm'] == arm)}/12"
                for arm in ("A", "B")
            )
            + "。\n"
        )
    else:
        text += "任务完成率和真实模型状态保留率：未测。回放有意使用相同 Read 轨迹，因此不产生虚构的重复读取下降。\n"
    return write_report(directory, text)
