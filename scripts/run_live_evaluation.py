"""Fast bounded live evaluation. Persist each outcome; never select scores after observing them."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from devflow.benchmarks.common import DATA, load_data, write_csv
from devflow.benchmarks.context_ab import live_task
from devflow.benchmarks.paid import BudgetedLLM, BudgetLedger
from devflow.config import Config
from devflow.tools import make_tools


def save_balance(cfg, directory, name):
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": "Bearer " + cfg.api_key.get_secret_value()},
        )
        response.raise_for_status()
        data = response.json()
    (directory / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return float(next(r["total_balance"] for r in data["balance_infos"] if r["currency"] == "CNY"))


def tool_case(case, directory):
    cfg = Config.load()
    tools = {t.name: t for t in make_tools(cfg)}
    valid_input = True
    try:
        tools[case["expected_tool"]].args_schema.model_validate(case["arguments"])
    except ValidationError:
        valid_input = False
    row = {
        "case_id": case["id"],
        "expected_tool": case["expected_tool"],
        "stratum": "normal_schema_input" if valid_input else "intentional_invalid_input",
        "selected_tool": "",
        "selection_correct": 0,
        "schema_valid": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "error": "",
    }
    started = time.monotonic()
    try:
        response = BudgetedLLM(cfg, directory).invoke_with_tools(
            messages=[
                {
                    "role": "system",
                    "content": "Choose exactly one of the supplied coding tools for the requested operation. Return its structured function call. For explicit invalid-input tests preserve the requested parameters. Do not execute tools.",
                },
                {"role": "user", "content": case["prompt"]},
            ],
            tools=[t.schema() for t in tools.values()],
            tool_choice="required",
            temperature=0,
            max_tokens=512,
        )
        row.update(
            input_tokens=response.usage.get("prompt_tokens", 0),
            output_tokens=response.usage.get("completion_tokens", 0),
            response_model=response.model,
            call_count=len(response.tool_calls),
        )
        calls = [{"name": c.name, "arguments": c.arguments} for c in response.tool_calls]
        row["raw_calls"] = json.dumps(calls, ensure_ascii=False)
        if response.tool_calls:
            call = response.tool_calls[0]
            row["selected_tool"] = call.name
            row["selection_correct"] = int(call.name == case["expected_tool"] and len(calls) == 1)
            if call.name in tools:
                try:
                    tools[call.name].args_schema.model_validate_json(call.arguments)
                    row["schema_valid"] = 1
                except ValidationError:
                    pass
    except Exception as exc:
        row["error"] = type(exc).__name__
    row["duration_seconds"] = round(time.monotonic() - started, 3)
    (directory / "tool-results" / (case["id"] + ".json")).write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return row


def context_job(task, arm, directory):
    cfg = Config.load().model_copy(
        update={
            "allow_shell": True,
            "max_steps": 5,
            "context_window": 16000,
            "reserve_tokens": 1024,
            "output_max_bytes": 4096,
            "output_max_lines": 100,
            "request_timeout": 35,
        }
    )
    root = (directory / "workspaces" / task["id"] / arm).resolve()
    # All runtime work stays in separate worker processes: upstream stdout redirection is global.
    import devflow.benchmarks.context_ab as context_module

    original = context_module.DevFlowController
    context_module.DevFlowController = lambda local, **kwargs: original(
        local, **kwargs, llm=BudgetedLLM(local, directory)
    )
    try:
        rows, score = live_task(cfg, task, root, arm)
        (root / "result.json").write_text(
            json.dumps({"rows": rows, "score": score}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return rows, score
    finally:
        context_module.DevFlowController = original


def summarize(directory):
    tool_rows = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((directory / "tool-results").glob("*.json"))
    ]
    rows, scores = [], []
    retry_complete = all(
        (directory / "workspaces" / "context-00-infra-retry" / arm / "result.json").exists()
        for arm in ("A", "B")
    )
    for path in sorted((directory / "workspaces").glob("*/*/result.json")):
        task_name = path.parent.parent.name
        if (task_name == "context-00" and retry_complete) or (
            task_name.endswith("-infra-retry") and not retry_complete
        ):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            if (
                row["input_tokens"] == ""
                and row["status"] == "ContextBudgetExceeded"
                and row.get("estimated_input_tokens", 0) == 0
            ):
                # Production guard raises before invoking the provider. Retain the failed
                # round, accounting for zero paid requests rather than dropping it.
                row["input_tokens"] = 0
                row["token_source"] = "no_request_context_guard"
        if task_name.endswith("-infra-retry"):
            data["score"]["task"] = "context-00"
            for row in data["rows"]:
                row["task"] = "context-00"
        rows.extend(data["rows"])
        scores.append(data["score"])
    write_csv(directory / "tool_calling.csv", tool_rows)
    write_csv(directory / "context_ab.csv", rows)
    write_csv(directory / "state_scores.csv", scores)
    normal = [r for r in tool_rows if r["stratum"] == "normal_schema_input"]
    metrics = {
        "tool_cases": len(tool_rows),
        "tool_correct": sum(r["selection_correct"] for r in tool_rows),
        "normal_cases": len(normal),
        "normal_schema_pass": sum(r["schema_valid"] for r in normal),
        "normal_selection_correct": sum(r["selection_correct"] for r in normal),
        "tool_errors": sum(bool(r["error"]) for r in tool_rows),
        "context_arms_completed": len(scores),
        "context_rows": len(rows),
    }
    if scores:
        totals = {
            arm: sum(
                int(r["input_tokens"]) for r in rows if r["arm"] == arm and r["input_tokens"] != ""
            )
            for arm in ("A", "B")
        }
        metrics["context_input_tokens"] = totals
        metrics["context_all_usage_present"] = all(r["input_tokens"] != "" for r in rows)
        metrics["context_turn_statuses"] = {
            s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})
        }
        for arm in ("A", "B"):
            selected = [s for s in scores if s["arm"] == arm]
            metrics[arm] = {
                "tasks": len(selected),
                "completed": sum(s["completion"] for s in selected),
                "retained": sum(s["retained"] for s in selected),
                "state_points": sum(s["state_points"] for s in selected),
                "repeated_reads": sum(s["repeated_reads"] for s in selected),
            }
    (directory / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["tool", "context", "summary"], required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--budget-cap", type=float, default=12)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tool-results").mkdir(exist_ok=True)
    BudgetLedger(directory, cap=args.budget_cap)
    if args.phase == "summary":
        summarize(directory)
        print("balance_cny", save_balance(Config.load(), directory, "balance-after.json"))
        return
    if not (directory / "protocol.json").exists():
        # Freeze protocol and hashes before looking at evaluation outcomes.
        (directory / "protocol.json").write_text(
            json.dumps(
                {
                    "started": datetime.now(UTC).isoformat(),
                    "model": "deepseek-flash",
                    "thinking": "disabled",
                    "temperature": 0,
                    "budget_cap_cny": args.budget_cap,
                    "prices_peak_cny_per_million": {"input": 2, "output": 8},
                    "context_window": 16000,
                    "max_steps": 5,
                    "output_max_bytes": 4096,
                    "datasets": {
                        name: hashlib.sha256((DATA / name).read_bytes()).hexdigest()
                        for name in ["tool_calling_cases.jsonl", "context_tasks.jsonl"]
                    },
                    "tool_protocol": "240 fixed single-tool requests, 200 normal schema inputs and 40 intentional invalid; no model-generated commands executed",
                    "context_protocol": "12 fixed tasks x 20 rounds x 2 arms; independent fixtures; final-answer literal rubric and external functional assertions",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        save_balance(Config.load(), directory, "balance-before.json")
    if args.phase == "tool":
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [
                pool.submit(tool_case, case, directory)
                for case in load_data("tool_calling_cases.jsonl")
                if not (directory / "tool-results" / (case["id"] + ".json")).exists()
            ]
            for i, future in enumerate(as_completed(futures), 1):
                future.result()
                if i % 20 == 0:
                    print("tool_completed", i, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [
                pool.submit(context_job, task, arm, directory)
                for task in load_data("context_tasks.jsonl")
                for arm in ("A", "B")
                if not (directory / "workspaces" / task["id"] / arm / "result.json").exists()
            ]
            for i, future in enumerate(as_completed(futures), 1):
                rows, score = future.result()
                print("context_completed", i, score, flush=True)
    summarize(directory)


if __name__ == "__main__":
    main()
