import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from devflow.cli import app
from devflow.controller import DevFlowController
from devflow.observability.trace import redact


def response(text=None, calls=()):
    return SimpleNamespace(
        content=text,
        tool_calls=[SimpleNamespace(id=i, name=n, arguments=json.dumps(a)) for i, n, a in calls],
        model="test-model",
        usage={"prompt_tokens": 20, "completion_tokens": 5},
    )


class ScriptedLLM:
    model = "gpt-4"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke_with_tools(self, messages, tools, **kwargs):
        self.requests.append(json.loads(json.dumps(messages)))
        assert {tool["function"]["name"] for tool in tools} == {
            "Read",
            "Write",
            "Edit",
            "Grep",
            "Bash",
            "TodoWrite",
        }
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def test_real_upstream_loop_tools_history_resume(cfg):
    llm = ScriptedLLM(
        [
            response(calls=[("1", "Write", {"path": "x.txt", "content": "hello"})]),
            response(calls=[("2", "Read", {"path": "x.txt"})]),
            response("done"),
            response("second"),
        ]
    )
    controller = DevFlowController(cfg, new=True, llm=llm)
    result = controller.run_turn("write a greeting")
    assert result.status == "completed" and result.usage.requests == 3
    assert "hello" in llm.requests[2][-1]["content"]
    assert not controller.session.pending_calls()
    controller.run_turn("what did you do?")
    assert "write a greeting" in json.dumps(llm.requests[-1])
    resumed = DevFlowController(
        cfg, session_id=controller.session.session_id, llm=ScriptedLLM([response("resumed")])
    )
    assert resumed.session.messages()[-1]["content"] == "second"
    resumed.run_turn("continue")
    records = controller.trace.records()
    assert [e["call_id"] for e in records if e["event"] == "tool_call"] == ["1", "2"]
    assert [e["call_id"] for e in records if e["event"] == "tool_result"] == ["1", "2"]


def test_invalid_arguments_return_to_model(cfg):
    llm = ScriptedLLM(
        [response(calls=[("1", "Read", {"path": "x", "start_line": "wrong"})]), response("recover")]
    )
    controller = DevFlowController(cfg, new=True, llm=llm)
    assert controller.run_turn("read").text == "recover"
    assert "INVALID_PARAM" in llm.requests[-1][-1]["content"]


def test_model_failure_is_visible_and_user_request_durable(cfg):
    controller = DevFlowController(
        cfg, new=True, llm=ScriptedLLM([RuntimeError("network failure")])
    )
    with pytest.raises(RuntimeError, match="network failure"):
        controller.run_turn("unfinished work")
    assert controller.session.messages()[-1]["content"] == "unfinished work"


def test_todo_survives_resume(cfg):
    todo = {"summary": "work", "todos": [{"id": "1", "content": "fix", "status": "in_progress"}]}
    controller = DevFlowController(
        cfg,
        new=True,
        llm=ScriptedLLM([response(calls=[("t", "TodoWrite", todo)]), response("planned")]),
    )
    controller.run_turn("plan work")
    resumed = DevFlowController(cfg, session_id=controller.session.session_id)
    assert resumed.tools["TodoWrite"].snapshot == todo


def test_redaction_and_cli_without_credentials(tmp_path):
    assert redact({"api_key": "abc", "input_tokens": 3}) == {
        "api_key": "[REDACTED]",
        "input_tokens": 3,
    }
    assert "my-secret" not in redact("failed my-secret", ["my-secret"])
    runner = CliRunner()
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["--root", str(tmp_path), "sessions"]).exit_code == 0
