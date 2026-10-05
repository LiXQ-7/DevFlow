import json
from types import SimpleNamespace

import pytest

from devflow.benchmarks.common import load_data
from devflow.controller import DevFlowController
from devflow.session import SessionManager
from devflow.skills.loader import SkillsLoader


def test_exact_edit_preserves_crlf(tools, tmp_path):
    (tmp_path / "windows.txt").write_bytes(b"hello\r\nworld\r\n")
    result = tools["Edit"].execute(
        {"path": "windows.txt", "old_text": "hello\r\nworld", "new_text": "hi\r\nworld"}
    )
    assert result.status == "SUCCESS"
    assert (tmp_path / "windows.txt").read_bytes() == b"hi\r\nworld\r\n"
    assert (
        tools["Edit"]
        .execute({"path": "windows.txt", "old_text": "hi\nworld", "new_text": "x"})
        .error_code
        == "NOT_FOUND"
    )


def test_branch_mid_call_keeps_protocol_adjacent(tmp_path):
    session = SessionManager(tmp_path / "sessions")
    call = session.record_message(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
            ],
        }
    )
    session.record_message({"role": "tool", "tool_call_id": "a", "content": "old"})
    session.branch(call.id)
    session.recover_pending()
    assert [m["role"] for m in session.messages()] == ["assistant", "tool"]


def test_dataset_counts_and_unique_prompts():
    tools = load_data("tool_calling_cases.jsonl")
    assert len(tools) == 240 and len({c["id"] for c in tools}) == 240
    assert len({c["prompt"] for c in tools}) >= 160
    for name in ("Read", "Write", "Edit", "Grep", "Bash", "TodoWrite"):
        assert sum(c["expected_tool"] == name for c in tools) == 40
    contexts = load_data("context_tasks.jsonl")
    assert len(contexts) == 12 and all(len(t["prompts"]) == 20 for t in contexts)
    assert len(load_data("fault_cases.jsonl")) == 30


def test_skills_are_lazy(monkeypatch):
    loader = SkillsLoader()
    assert loader.match("请审查代码") == ["code-review"]
    assert "code-review" in loader.metadata()
    assert "先确定审查范围" in loader.load("code-review")
    with pytest.raises(ValueError):
        loader.load("../escape")


def test_multi_call_and_max_steps(cfg):
    class Model:
        model = "gpt-4"

        def invoke_with_tools(self, **kwargs):
            return SimpleNamespace(
                content=None,
                model=self.model,
                usage={},
                tool_calls=[
                    SimpleNamespace(
                        id="a", name="Write", arguments=json.dumps({"path": "a", "content": "a"})
                    ),
                    SimpleNamespace(id="b", name="Read", arguments=json.dumps({"path": "a"})),
                ],
            )

    cfg.max_steps = 1
    controller = DevFlowController(cfg, new=True, llm=Model())
    assert controller.run_turn("write then read").status == "max_steps"
    assert not controller.session.pending_calls()
    assert (cfg.project_root / "a").read_text() == "a"
