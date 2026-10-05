import json

import pytest

from devflow.config import Config
from devflow.context.policy import CodingContextPolicy, ContextBudgetExceeded
from devflow.session import SessionManager
from devflow.session.jsonl_store import ConcurrentSession, CorruptSession
from devflow.tools.base import ToolResult


def test_tree_branch_preserves_siblings(tmp_path):
    session = SessionManager(tmp_path / "sessions", project_root=tmp_path)
    a = session.record_message({"role": "user", "content": "A"})
    b = session.record_message({"role": "assistant", "content": "B"})
    c = session.record_message({"role": "user", "content": "C"})
    session.branch(b.id)
    d = session.record_message({"role": "user", "content": "D"})
    resumed = SessionManager(tmp_path / "sessions", session.session_id, tmp_path)
    assert c.id in {entry.id for entry in resumed.entries}
    assert [
        entry.id for entry in resumed.active_branch() if entry.id in {a.id, b.id, c.id, d.id}
    ] == [a.id, b.id, d.id]


def test_torn_tail_repair_and_second_resume(tmp_path):
    session = SessionManager(tmp_path)
    with session.store.path.open("ab") as stream:
        stream.write(b'{"id":"torn')
    with pytest.warns(RuntimeWarning):
        resumed = SessionManager(tmp_path, session.session_id)
    with pytest.warns(RuntimeWarning):
        resumed.record_message({"role": "user", "content": "after repair"})
    assert SessionManager(tmp_path, session.session_id).messages()[-1]["content"] == "after repair"


def test_interior_corruption_is_not_silently_skipped(tmp_path):
    session = SessionManager(tmp_path)
    with session.store.path.open("ab") as stream:
        stream.write(b"bad\n{}\n")
    with pytest.raises(CorruptSession):
        SessionManager(tmp_path, session.session_id)


def test_concurrent_writer_rejected(tmp_path):
    first = SessionManager(tmp_path)
    second = SessionManager(tmp_path, first.session_id)
    first.record_message({"role": "user", "content": "new"})
    with pytest.raises(ConcurrentSession):
        second.record_message({"role": "user", "content": "stale"})


def test_unknown_tool_result_is_never_reexecuted(tmp_path):
    session = SessionManager(tmp_path)
    session.record_message(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "x", "type": "function", "function": {"name": "Write", "arguments": "{}"}}
            ],
        }
    )
    assert list(session.recover_pending()) == ["x"]
    assert not session.pending_calls()
    assert "INTERRUPTED_UNKNOWN_OUTCOME" in session.messages()[-1]["content"]


def test_summary_keeps_calls_atomic_and_history_durable(tmp_path):
    cfg = Config(
        project_root=tmp_path, context_window=6000, reserve_tokens=1000, keep_recent_rounds=2
    )
    policy = CodingContextPolicy(cfg)
    session = SessionManager(tmp_path / "sessions")
    for i in range(8):
        session.record_message({"role": "user", "content": f"constraint-{i}"})
        session.record_message(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": str(i),
                        "type": "function",
                        "function": {"name": "Read", "arguments": '{"path":"x"}'},
                    }
                ],
            }
        )
        session.record_message(
            {
                "role": "tool",
                "tool_call_id": str(i),
                "content": json.dumps(
                    {
                        "status": "SUCCESS",
                        "text": "very long code\n" * 350,
                        "data": {"path": "x", "sha256": "hash", "start_line": 1, "end_line": 350},
                    }
                ),
            }
        )
        session.record_message({"role": "assistant", "content": "inspected"})
    original_ids = [e.id for e in session.entries]
    messages, data = policy.compact(session.messages())
    assert data and data["tokens_after"] < data["tokens_before"]
    session.compact(data)
    assert [e.id for e in session.entries][: len(original_ids)] == original_ids
    assert SessionManager(tmp_path / "sessions", session.session_id).messages() == messages
    encoded = json.dumps(messages)
    for i in range(8):
        assert f"constraint-{i}" in encoded
    assert not session.pending_calls()


def test_single_huge_turn_refused(cfg):
    policy = CodingContextPolicy(cfg)
    with pytest.raises(ContextBudgetExceeded):
        policy.compact([{"role": "user", "content": "huge " * 50000}])


def test_long_single_line_and_5000_line_output_saved(cfg):
    policy = CodingContextPolicy(cfg)
    for text in ("中" * 50000, "log line\n" * 5000):
        response = policy.truncate("Bash", ToolResult(text=text, data={"raw": text}))
        assert response.status == "PARTIAL"
        assert len(response.text.encode("utf-8")) <= cfg.output_max_bytes + 5
        full = json.loads(
            (cfg.project_root / response.data["full_output_path"]).read_text(encoding="utf-8")
        )
        assert json.loads(full["output"])["text"] == text
        assert "raw" not in response.data


def test_line_budget_applies_before_json_escaping(cfg):
    policy = CodingContextPolicy(cfg)
    result = policy.truncate("Read", ToolResult(text="x\n" * 300))
    assert result.status == "PARTIAL"
    assert len(result.text.splitlines()) <= cfg.output_max_lines


def test_complete_corrupt_last_line_is_rejected(tmp_path):
    session = SessionManager(tmp_path)
    with session.store.path.open("ab") as stream:
        stream.write(b"bad record\n")
    with pytest.raises(CorruptSession):
        SessionManager(tmp_path, session.session_id)
