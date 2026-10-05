"""Thirty real worker failures, resumed using the production session/controller code."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from devflow.config import Config
from devflow.controller import DevFlowController

from .common import load_data, metadata, report_dir, write_csv, write_report


class FaultModel:
    model = "gpt-4"

    def __init__(self, kind, index):
        self.kind, self.index = kind, index

    def invoke_with_tools(self, messages, tools, **kwargs):
        if self.kind == "model_exception":
            raise ConnectionError(f"injected provider failure {self.index}")
        arguments = {"path": f"effect-{self.index}.txt", "content": "side effect occurred"}
        name = "Write"
        if self.index % 2:
            name = "Bash"
            program = f"from pathlib import Path; Path('effect-{self.index}.txt').write_text('side effect occurred')"
            if self.index == 9:
                program += "; import time; time.sleep(5)"
            arguments = {
                "command": f'python -c "{program}"',
                "timeout": 1 if self.index == 9 else 10,
            }
        return SimpleNamespace(
            content=None,
            model=self.model,
            usage={},
            tool_calls=[
                SimpleNamespace(id=f"call-{self.index}", name=name, arguments=json.dumps(arguments))
            ],
        )


class ResumeModel:
    model = "gpt-4"

    def invoke_with_tools(self, messages, tools, **kwargs):
        assert any(message["role"] == "user" for message in messages)
        return SimpleNamespace(
            content="resumed from durable history", model=self.model, usage={}, tool_calls=[]
        )


def worker(root, kind, index):
    cfg = Config(project_root=root, allow_shell=True)
    controller = DevFlowController(cfg, new=True, llm=FaultModel(kind, index))
    if kind == "append_process_exit":
        controller.on_message({"role": "user", "content": f"task {index}"})
        todo = {
            "summary": f"plan {index}",
            "todos": [{"id": "1", "content": "resume work", "status": "in_progress"}],
        }
        controller.session.append("todo_snapshot", todo)
        # Vary whether a torn final suffix follows the last consistent record.
        if index % 2:
            with controller.session.store.path.open("ab") as stream:
                stream.write(b'{"id":"torn')
                stream.flush()
                os.fsync(stream.fileno())
        os._exit(73)
    if kind == "tool_process_exit":
        original = controller.execute

        def interrupt(name, args):
            result = original(name, args)
            assert result.status == "SUCCESS" or result.error_code == "TIMEOUT"
            os._exit(72)  # Tool side effect exists; result has not reached the journal.

        controller.execute = interrupt
    try:
        controller.run_turn(f"task {index}: create evidence")
    except ConnectionError:
        os._exit(71)
    raise RuntimeError("Injection did not fire")


def run(output):
    directory = report_dir(output, "recovery", "process")
    rows = []
    for case in load_data("fault_cases.jsonl"):
        root = (directory / "workspaces" / case["id"]).resolve()
        root.mkdir(parents=True)
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "devflow.benchmarks.fault_injection",
                "--worker",
                str(root),
                case["kind"],
                str(case["index"]),
            ],
            capture_output=True,
            timeout=30,
        )
        (root / "worker.log").write_bytes(child.stdout + child.stderr)
        row = {
            "case_id": case["id"],
            "kind": case["kind"],
            "process_exit_code": child.returncode,
            "successful_resume": 0,
            "uncertain_side_effect": 0,
            "auto_replayed": 0,
            "error": "",
        }
        expected_exit = {"model_exception": 71, "tool_process_exit": 72, "append_process_exit": 73}[
            case["kind"]
        ]
        try:
            if child.returncode != expected_exit:
                raise RuntimeError(f"Unexpected worker exit {child.returncode}")
            controller = DevFlowController(Config(project_root=root), llm=ResumeModel())
            assert controller.session.messages()
            row["uncertain_side_effect"] = int(bool(controller.uncertain_calls))
            if case["kind"] == "tool_process_exit":
                assert controller.uncertain_calls
                assert (root / f"effect-{case['index']}.txt").read_text() == "side effect occurred"
            if case["kind"] == "append_process_exit":
                assert controller.tools["TodoWrite"].snapshot["todos"][0]["status"] == "in_progress"
            assert (
                controller.run_turn("Continue; verify unknown effects before retrying").status
                == "completed"
            )
            # Second restart proves the repaired tail remains appendable.
            again = DevFlowController(Config(project_root=root))
            assert again.session.messages()[-1]["content"] == "resumed from durable history"
            row["successful_resume"] = 1
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    write_csv(directory / "fault_injection.csv", rows)
    successful = sum(row["successful_resume"] for row in rows)
    uncertain = sum(row["uncertain_side_effect"] for row in rows)
    metadata(
        directory,
        dataset="fault_cases.jsonl",
        mode="real_worker_exit_scripted_model",
        total=len(rows),
        successful_resume=successful,
        uncertain_side_effect=uncertain,
    )
    return write_report(
        directory,
        f"# Recovery benchmark\n\n模型异常、Tool 后退出、append 后退出各 10 次，共 {len(rows)} 次。\n\n"
        f"从最近一致历史恢复并继续：{successful}/{len(rows)}（{successful / len(rows):.2%}）。\n\n"
        f"检测到副作用结果不确定：{uncertain} 次；自动重放：0。成功定义是安全恢复协议状态并能继续，不是 exactly-once 或原任务自动完成。\n\n"
        "真实子进程 os._exit 模拟强制退出；模型响应使用离线替身。5 次包含 JSONL 尾部半行。原始日志及失败案例保留于 workspaces 和 fault_injection.csv。\n",
    )


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
    else:
        print(run(Path("benchmark-results")))
