import json
import tempfile
from pathlib import Path

from pydantic import ValidationError

from devflow.observability.trace import TraceLogger
from devflow.tools import make_tools

from .common import load_data, metadata, report_dir, write_csv, write_report


def run(cfg, output, live=False):
    directory = report_dir(output, "tool", "live" if live else "offline")
    dataset = load_data("tool_calling_cases.jsonl")
    llm = None
    if live:
        from devflow.runtime.hello_agents_adapter import make_llm

        llm = make_llm(cfg)
    trace = TraceLogger(
        directory / "trace.jsonl", directory.name, (cfg.api_key.get_secret_value(),)
    )
    rows = []
    for case in dataset:
        with tempfile.TemporaryDirectory(prefix="devflow-tool-") as temp:
            root = Path(temp)
            for name, content in case["fixture"].items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
            (root / case["binary"]).write_bytes(b"\xff\xfe\x00")
            local = cfg.model_copy(
                update={"project_root": root, "allow_shell": cfg.allow_shell if live else True}
            )
            tools = {tool.name: tool for tool in make_tools(local)}
            selected, arguments = case["expected_tool"], case["arguments"]
            row = {
                "case_id": case["id"],
                "mode": "live" if live else "offline_fixture",
                "expected_tool": case["expected_tool"],
                "expected_outcome": case["expected_outcome"],
            }
            request_error = ""
            calls_count = 1
            if llm:
                try:
                    reply = llm.invoke_with_tools(
                        messages=[
                            {
                                "role": "system",
                                "content": "Select exactly one coding tool for the requested operation. Return a function call. Do not execute it. Negative tests intentionally request invalid inputs; preserve those inputs.",
                            },
                            {"role": "user", "content": case["prompt"]},
                        ],
                        tools=[tool.schema() for tool in tools.values()],
                        temperature=cfg.temperature,
                        tool_choice="required",
                    )
                    calls_count = len(reply.tool_calls)
                    selected = reply.tool_calls[0].name if reply.tool_calls else ""
                    arguments = (
                        json.loads(reply.tool_calls[0].arguments) if reply.tool_calls else {}
                    )
                    row["input_tokens"] = (reply.usage or {}).get("prompt_tokens")
                    row["response_model"] = reply.model
                except Exception as exc:
                    selected, arguments, request_error = "", {}, type(exc).__name__
            schema_valid = False
            if selected in tools:
                try:
                    tools[selected].args_schema.model_validate(arguments)
                    schema_valid = True
                except ValidationError:
                    pass
            result = tools[selected].execute(arguments) if selected in tools else None
            outcome = (result.error_code or result.status) if result else "NO_TOOL"
            row.update(
                selected_tool=selected,
                call_count=calls_count,
                schema_valid=int(schema_valid),
                selection_correct=int(selected == case["expected_tool"] and calls_count == 1),
                outcome=outcome,
                execution_success=int(result is not None and result.status == "SUCCESS"),
                fixture_outcome_match=int(outcome == case["expected_outcome"]),
                error=request_error,
            )
            trace.emit("tool_case", {**row, "arguments": arguments})
            rows.append(row)
    write_csv(directory / "tool_calling.csv", rows)
    # Metrics read the same observable records saved as evidence.
    records = trace.records()
    total = len(records)
    selection = sum(r["selection_correct"] for r in records) / total
    schema = sum(r["schema_valid"] for r in records) / total
    outcome = sum(r["fixture_outcome_match"] for r in records)
    execution = sum(r["execution_success"] for r in records) / total
    metadata(
        directory,
        cfg,
        "tool_calling_cases.jsonl",
        mode="live" if live else "offline_fixture",
        cases=total,
        note="Includes intentional invalid-schema cases; report positive and negative strata separately.",
    )
    positive = [r for r in records if r["expected_outcome"] != "INVALID_PARAM"]
    positive_schema = sum(r["schema_valid"] for r in positive) / len(positive)
    text = f"# Tool benchmark\n\n模式：{'真实模型' if live else '离线标注参数执行（不测模型选择）'}；{total} 条。\n\n"
    if live:
        text += f"工具选择准确率：{selection:.2%}；全量 Schema 通过率：{schema:.2%}；合法输入子集 Schema 通过率：{positive_schema:.2%}。\n\n"
        text += f"工具执行 SUCCESS 比例：{execution:.2%}。负例的正确拒绝不属于执行 SUCCESS。\n\n"
    else:
        text += "工具选择准确率：未测。模型 Schema 通过率：未测。\n\n"
    text += f"预期执行语义符合：{outcome}/{total}。数据包含刻意非法参数；全量 Schema 率不得混作普通请求模型能力。\n\n原始证据：tool_calling.csv、trace.jsonl、metadata.json。失败样本保留在 CSV。\n"
    return write_report(directory, text)
