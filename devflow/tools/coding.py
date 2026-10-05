"""Six coding tools with bounded observations and deterministic failure semantics."""

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Literal

import regex as safe_regex
from filelock import FileLock
from pydantic import Field, model_validator

from .base import Args, BaseCodingTool, ToolFailure, ToolResult
from .safety import EXCLUDED, atomic_write, check_command, safe_path, writable_path


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class ReadArgs(Args):
    path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    max_bytes: int = Field(default=12000, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class ReadTool(BaseCodingTool):
    name = "Read"
    description = "Read a UTF-8 file with line numbers and SHA256. Prefer small line ranges."
    args_schema = ReadArgs
    default_lines = 200

    def run(self, args):
        path = safe_path(self.root, args.path)
        # Streaming hash and iteration avoid loading a large file into memory.
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                hasher.update(chunk)
        selected, size, last, total, clipped = [], 0, args.start_line - 1, 0, False
        end = (
            args.end_line if args.end_line is not None else args.start_line + self.default_lines - 1
        )
        with path.open("r", encoding="utf-8", newline="") as stream:
            for number, line in enumerate(stream, 1):
                total = number
                if number < args.start_line or number > end:
                    continue
                raw = line.encode("utf-8")
                remaining = max(0, args.max_bytes - size)
                if len(raw) > remaining:
                    clipped = True
                text = raw[:remaining].decode("utf-8", errors="ignore")
                if text:
                    selected.append(f"{number}: {text.rstrip()}")
                    size += len(text.encode("utf-8"))
                    last = number
        partial = clipped or total > end
        data = {
            "path": str(path.relative_to(self.root)),
            "start_line": args.start_line,
            "end_line": last,
            "total_lines": total,
            "sha256": hasher.hexdigest(),
            "mtime_ns": path.stat().st_mtime_ns,
            "truncated": partial,
            "next_start_line": (last if clipped else last + 1) if partial else None,
        }
        return ToolResult(
            status="PARTIAL" if partial else "SUCCESS", text="\n".join(selected), data=data
        )


class WriteArgs(Args):
    path: str
    content: str
    overwrite: bool = False


class WriteTool(BaseCodingTool):
    name = "Write"
    description = "Create a UTF-8 file. Replacing an existing file requires overwrite=true."
    args_schema = WriteArgs

    def run(self, args):
        path = writable_path(self.root, args.path)
        raw = args.content.encode("utf-8")
        lock_dir = self.output_dir.parent / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(lock_dir / (digest(str(path).encode()) + ".lock")), timeout=10):
                atomic_write(path, raw, overwrite=args.overwrite)
        except FileExistsError:
            raise ToolFailure("ALREADY_EXISTS", "Use overwrite=true to replace existing file")
        return ToolResult(
            text="File written",
            data={"path": args.path, "bytes_written": len(raw), "sha256": digest(raw)},
        )


class EditArgs(Args):
    path: str
    old_text: str = Field(min_length=1)
    new_text: str
    expected_hash: str | None = None
    expected_mtime_ns: int | None = None


class EditTool(BaseCodingTool):
    name = "Edit"
    description = "Exactly replace one occurrence in a file; optional hash/mtime optimistic lock."
    args_schema = EditArgs

    def run(self, args):
        path = writable_path(self.root, args.path)
        lock_dir = self.output_dir.parent / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        with FileLock(str(lock_dir / (digest(str(path).encode()) + ".lock")), timeout=10):
            raw = path.read_bytes()
            old_hash = digest(raw)
            if args.expected_hash is not None and args.expected_hash != old_hash:
                raise ToolFailure("CONFLICT", "File hash changed; Read it again")
            if (
                args.expected_mtime_ns is not None
                and args.expected_mtime_ns != path.stat().st_mtime_ns
            ):
                raise ToolFailure("CONFLICT", "File modification time changed")
            text = raw.decode("utf-8")
            count = text.count(args.old_text)
            if count != 1:
                raise ToolFailure(
                    "NOT_FOUND" if count == 0 else "CONFLICT", f"Expected one match, found {count}"
                )
            updated = text.replace(args.old_text, args.new_text, 1).encode("utf-8")
            if digest(path.read_bytes()) != old_hash:
                raise ToolFailure("CONFLICT", "Concurrent change detected")
            start = text[: text.index(args.old_text)].count("\n") + 1
            atomic_write(path, updated)
        return ToolResult(
            text="One occurrence replaced",
            data={
                "path": args.path,
                "replacements": 1,
                "old_hash": old_hash,
                "new_hash": digest(updated),
                "modified_lines": [start, start + args.new_text.count("\n")],
            },
        )


class GrepArgs(Args):
    query: str = Field(min_length=1)
    path: str = "."
    regex: bool = False
    max_results: int = Field(default=50, ge=1, le=1000)


class GrepTool(BaseCodingTool):
    name = "Grep"
    description = "Search code by literal text or regex; return path, line and preview, excluding build/state directories."
    args_schema = GrepArgs

    def run(self, args):
        target = safe_path(self.root, args.path)
        if not target.exists():
            raise FileNotFoundError(target)
        try:
            pattern = safe_regex.compile(args.query if args.regex else re.escape(args.query))
        except safe_regex.error as exc:
            raise ToolFailure("INVALID_PARAM", str(exc))
        matches, total = [], 0
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if shutil.which("rg"):
            return self._ripgrep(args, target)
        backend = "python"
        output_path = self.output_dir / ("grep-" + uuid.uuid4().hex + ".jsonl")
        output_path.write_text("", encoding="utf-8")
        if target.is_dir():
            files = []
            for directory, dirs, names in os.walk(target, followlinks=False):
                dirs[:] = [
                    d for d in dirs if d not in EXCLUDED and not (Path(directory) / d).is_symlink()
                ]
                files.extend(Path(directory) / name for name in names)
        else:
            files = [target]
        for file in sorted(files):
            if file.is_symlink() or not file.resolve().is_relative_to(self.root):
                continue
            if any(part in EXCLUDED for part in file.relative_to(self.root).parts):
                continue
            try:
                if file.stat().st_size > 5_000_000:
                    continue
                with file.open(encoding="utf-8") as stream:
                    for number, line in enumerate(stream, 1):
                        if "\x00" in line:
                            break
                        if pattern.search(line, timeout=0.05):
                            total += 1
                            with output_path.open("a", encoding="utf-8") as output:
                                output.write(
                                    json.dumps(
                                        {
                                            "path": str(file.relative_to(self.root)),
                                            "line": number,
                                            "text": line.rstrip(),
                                        },
                                        ensure_ascii=False,
                                    )
                                    + "\n"
                                )
                            if len(matches) < args.max_results:
                                matches.append(
                                    {
                                        "path": str(file.relative_to(self.root)),
                                        "line": number,
                                        "text": line.rstrip()[:500],
                                    }
                                )
            except (UnicodeError, PermissionError):
                continue
            except TimeoutError:
                raise ToolFailure("TIMEOUT", "Regex exceeded per-line time budget")
        partial = total > len(matches)
        return ToolResult(
            status="PARTIAL" if partial else "SUCCESS",
            text="\n".join(f"{m['path']}:{m['line']}: {m['text']}" for m in matches),
            data={
                "matches": matches,
                "total_seen": total,
                "returned": len(matches),
                "backend": backend,
                "full_output_path": str(output_path.relative_to(self.root)),
                "truncated": partial,
            },
        )

    def _ripgrep(self, args, target):
        output_path = self.output_dir / ("grep-" + uuid.uuid4().hex + ".jsonl")
        command = [
            "rg",
            "--json",
            "--line-number",
            "--no-heading",
            "--hidden",
            "--no-ignore",
            "--max-filesize",
            "5M",
            "--sort",
            "path",
        ]
        if not args.regex:
            command.append("--fixed-strings")
        for excluded in sorted(EXCLUDED):
            command += ["--glob", f"!**/{excluded}/**"]
        command += ["--", args.query, str(target)]
        with output_path.open("wb") as output:
            try:
                result = subprocess.run(
                    command,
                    cwd=self.root,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise ToolFailure("TIMEOUT", "Search exceeded 20 seconds")
        if result.returncode not in (0, 1):
            raise ToolFailure(
                "INVALID_PARAM", result.stderr.decode("utf-8", errors="replace")[:1000]
            )
        matches, total = [], 0
        with output_path.open(encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                if event["type"] != "match":
                    continue
                data = event["data"]
                if "text" not in data["path"] or "text" not in data["lines"]:
                    continue
                path = Path(data["path"]["text"])
                if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                    continue
                if any(part in EXCLUDED for part in path.relative_to(self.root).parts):
                    continue
                total += 1
                if len(matches) < args.max_results:
                    matches.append(
                        {
                            "path": str(path.relative_to(self.root)),
                            "line": data["line_number"],
                            "text": data["lines"]["text"].rstrip()[:500],
                        }
                    )
        return ToolResult(
            status="PARTIAL" if total > len(matches) else "SUCCESS",
            text="\n".join(f"{m['path']}:{m['line']}: {m['text']}" for m in matches),
            data={
                "matches": matches,
                "total_seen": total,
                "returned": len(matches),
                "backend": "ripgrep",
                "full_output_path": str(output_path.relative_to(self.root)),
                "truncated": total > len(matches),
            },
        )


class BashArgs(Args):
    command: str = Field(min_length=1, max_length=8000)
    cwd: str = "."
    timeout: int = Field(default=30, ge=1, le=300)


def stop_process(process):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


class BashTool(BaseCodingTool):
    name = "Bash"
    description = "Execute a local shell command (PowerShell on Windows, bash on Unix), with timeout. Requires explicit shell enablement."
    args_schema = BashArgs
    allowed = False
    timeout_limit = 30

    def run(self, args):
        cwd = safe_path(self.root, args.cwd)
        check_command(args.command, self.allowed)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex
        out_path, err_path = (
            self.output_dir / (name + suffix) for suffix in (".stdout", ".stderr")
        )
        if os.name == "nt":
            command = [
                shutil.which("pwsh") or "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                args.command,
            ]
            options = {
                "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            }
        else:
            command = ["/bin/bash", "-c", args.command]
            options = {"start_new_session": True}
        env = dict(os.environ)
        # Do not pass provider credentials into child commands.
        for key in list(env):
            if re.search(r"(API_KEY|AUTHORIZATION|COOKIE|SECRET|PASSWORD|ACCESS_TOKEN)", key, re.I):
                env.pop(key)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        timed_out = False
        with out_path.open("wb") as out, err_path.open("wb") as err:
            process = subprocess.Popen(command, cwd=cwd, stdout=out, stderr=err, env=env, **options)
            try:
                process.wait(timeout=min(args.timeout, self.timeout_limit))
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_process(process)
            except BaseException:
                stop_process(process)
                raise

        def tail(path):
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 6000))
                return stream.read(6000).decode("utf-8", errors="replace")

        stdout, stderr = tail(out_path), tail(err_path)
        data = {
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "full_output_path": str(out_path.relative_to(self.root)),
            "full_stderr_path": str(err_path.relative_to(self.root)),
            "output_bytes": out_path.stat().st_size + err_path.stat().st_size,
            "truncated": out_path.stat().st_size > 6000 or err_path.stat().st_size > 6000,
        }
        text = f"exit_code={process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        return ToolResult(
            status="ERROR"
            if timed_out or process.returncode
            else ("PARTIAL" if data["truncated"] else "SUCCESS"),
            text=text,
            data=data,
            error_code="TIMEOUT"
            if timed_out
            else ("EXECUTION_ERROR" if process.returncode else None),
        )


class Todo(Args):
    id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoArgs(Args):
    summary: str
    todos: list[Todo] = Field(max_length=100)

    @model_validator(mode="after")
    def unique(self):
        if len({todo.id for todo in self.todos}) != len(self.todos):
            raise ValueError("Todo IDs must be unique")
        if sum(todo.status == "in_progress" for todo in self.todos) > 1:
            raise ValueError("At most one in_progress todo")
        return self


class TodoWriteTool(BaseCodingTool):
    name = "TodoWrite"
    description = "Replace the structured task plan. Unique IDs, pending/in_progress/completed, at most one in progress."
    args_schema = TodoArgs

    def __init__(self, root, output_dir):
        super().__init__(root, output_dir)
        self.snapshot = {"summary": "", "todos": []}

    def run(self, args):
        self.snapshot = args.model_dump()
        stats = {
            state: sum(t.status == state for t in args.todos)
            for state in ("pending", "in_progress", "completed")
        }
        return ToolResult(
            text=json.dumps(self.snapshot, ensure_ascii=False),
            data={**self.snapshot, "stats": stats},
        )


def make_tools(config):
    result = [
        cls(config.project_root, config.state_dir / "outputs")
        for cls in (ReadTool, WriteTool, EditTool, GrepTool, BashTool, TodoWriteTool)
    ]
    result[4].allowed = config.allow_shell
    result[4].timeout_limit = config.command_timeout
    return result
