import hashlib
import shutil

import pytest


def test_read_ranges_and_unicode(tools, tmp_path):
    (tmp_path / "中文.txt").write_text("一\n二\n三\n", encoding="utf-8")
    result = tools["Read"].execute({"path": "中文.txt", "start_line": 2, "end_line": 2})
    assert result.status == "PARTIAL" and result.text == "2: 二"
    assert result.data["next_start_line"] == 3


@pytest.mark.parametrize(
    "name,args",
    [
        ("Read", {"path": "../escape"}),
        ("Write", {"path": "../escape", "content": "x"}),
        ("Edit", {"path": "../escape", "old_text": "x", "new_text": "y"}),
        ("Grep", {"path": "../", "query": "x"}),
        ("Bash", {"cwd": "../", "command": "echo x"}),
        ("Write", {"path": ".git/config", "content": "x"}),
        ("Read", {"path": ".devflow/sessions/x"}),
    ],
)
def test_workspace_boundaries(tools, name, args):
    assert tools[name].execute(args).error_code == "PERMISSION"


def test_symlink_escape(tools, tmp_path):
    try:
        (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink permission")
    assert tools["Write"].execute({"path": "escape/x", "content": "x"}).error_code == "PERMISSION"


def test_write_and_edit_conflicts(tools, tmp_path):
    assert tools["Write"].execute({"path": "src/a.txt", "content": "abc abc"}).status == "SUCCESS"
    assert (
        tools["Write"].execute({"path": "src/a.txt", "content": "x"}).error_code == "ALREADY_EXISTS"
    )
    args = {"path": "src/a.txt", "old_text": "abc", "new_text": "z"}
    assert tools["Edit"].execute(args).error_code == "CONFLICT"
    assert tools["Edit"].execute({**args, "old_text": "missing"}).error_code == "NOT_FOUND"
    assert tools["Edit"].execute({**args, "expected_hash": "stale"}).error_code == "CONFLICT"
    args["old_text"] = "abc abc"
    args["expected_hash"] = hashlib.sha256(b"abc abc").hexdigest()
    assert tools["Edit"].execute(args).data["replacements"] == 1
    assert (tmp_path / "src/a.txt").read_text() == "z"
    assert not list((tmp_path / "src").glob(".devflow-*"))


@pytest.mark.parametrize("fallback", [False, True])
def test_grep_partial_and_exclusions(tools, tmp_path, monkeypatch, fallback):
    if fallback:
        monkeypatch.setattr(shutil, "which", lambda _: None)
    (tmp_path / "a.py").write_text("hit\nhit\nhit\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/x").write_text("hit")
    result = tools["Grep"].execute({"query": "hit", "max_results": 2})
    assert result.status == "PARTIAL"
    assert result.data["total_seen"] == 3 and result.data["returned"] == 2
    assert tools["Grep"].execute({"query": "[", "regex": True}).error_code == "INVALID_PARAM"


@pytest.mark.parametrize(
    "command", ["rm -rf /", "git reset --hard", "Remove-Item x -Recurse", "git clean -fd"]
)
def test_dangerous_commands_blocked(tools, command):
    assert tools["Bash"].execute({"command": command}).error_code == "PERMISSION"


def test_shell_requires_enablement(tools):
    tools["Bash"].allowed = False
    assert tools["Bash"].execute({"command": "echo hello"}).error_code == "APPROVAL_REQUIRED"


def test_shell_output_and_timeout(tools, tmp_path):
    result = tools["Bash"].execute({"command": 'python -c "print(123)"'})
    assert result.status == "SUCCESS", result
    assert "123" in result.data["stdout"]
    assert (tmp_path / result.data["full_output_path"]).exists()
    result = tools["Bash"].execute(
        {"command": 'python -c "import time; time.sleep(10)"', "timeout": 1}
    )
    assert result.error_code == "TIMEOUT"


def test_schema_and_todo(tools):
    assert tools["Read"].execute({"path": "x", "start_line": "1"}).error_code == "INVALID_PARAM"
    assert tools["Read"].execute({"path": "x", "unknown": True}).error_code == "INVALID_PARAM"
    args = {
        "summary": "plan",
        "todos": [
            {"id": "1", "content": "a", "status": "in_progress"},
            {"id": "2", "content": "b", "status": "in_progress"},
        ],
    }
    assert tools["TodoWrite"].execute(args).error_code == "INVALID_PARAM"
    args["todos"][1]["status"] = "pending"
    assert tools["TodoWrite"].execute(args).data["stats"]["in_progress"] == 1
