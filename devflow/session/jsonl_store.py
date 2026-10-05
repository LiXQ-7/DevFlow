"""Fsync'd event records; only a torn final line can be recovered automatically."""

import os
import re
import warnings
from pathlib import Path

from filelock import FileLock
from pydantic import ValidationError

from .models import SessionEntry


class CorruptSession(RuntimeError):
    pass


class ConcurrentSession(RuntimeError):
    pass


class JsonlStore:
    def __init__(self, directory: Path, session_id: str):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", session_id):
            raise ValueError("Invalid session ID")
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (session_id + ".jsonl")
        self.session_id = session_id
        self.lock = FileLock(str(self.path) + ".lock", timeout=5)

    def _load(self, repair=False):
        if not self.path.exists():
            return []
        entries, valid_bytes = [], 0
        raw = self.path.read_bytes()
        lines = raw.splitlines(keepends=True)
        seen = set()
        for index, line in enumerate(lines):
            try:
                if not line.endswith(b"\n"):
                    raise ValueError("Uncommitted line")
                entry = SessionEntry.model_validate_json(line)
            except (ValidationError, ValueError):
                if index != len(lines) - 1 or line.endswith(b"\n"):
                    raise CorruptSession(f"Invalid interior record at line {index + 1}")
                warnings.warn("Ignored torn final session record", RuntimeWarning)
                if repair:
                    # Only discard the uncommitted suffix; all complete events stay append-only.
                    with self.path.open("r+b") as stream:
                        stream.truncate(valid_bytes)
                        stream.flush()
                        os.fsync(stream.fileno())
                break
            if entry.session_id != self.session_id or entry.id in seen:
                raise CorruptSession("Session identity or duplicate event ID")
            if entry.parent_id is not None and entry.parent_id not in seen:
                raise CorruptSession("Missing parent or forward/cyclic reference")
            if entries and entry.parent_id is None:
                raise CorruptSession("Multiple root nodes")
            entries.append(entry)
            seen.add(entry.id)
            valid_bytes += len(line)
        return entries

    def load(self):
        with self.lock:
            return self._load()

    def append(self, entry, expected_last):
        with self.lock:
            entries = self._load(repair=True)
            actual_last = entries[-1].id if entries else None
            if actual_last != expected_last:
                raise ConcurrentSession("Session changed in another process; reload before writing")
            if entry.parent_id is not None and entry.parent_id not in {e.id for e in entries}:
                raise CorruptSession("Unknown parent")
            if entries and entry.parent_id is None:
                raise CorruptSession("Cannot append another root")
            with self.path.open("ab") as stream:
                stream.write((entry.model_dump_json() + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
