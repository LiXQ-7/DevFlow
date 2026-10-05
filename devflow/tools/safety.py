"""Workspace checks are a local policy, not an OS sandbox."""

import os
import re
import stat
import tempfile
from pathlib import Path

from .base import ToolFailure

EXCLUDED = {
    ".git",
    ".devflow",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "dist",
    "__pycache__",
    ".upstream",
}


def safe_path(root: Path, value: str, *, internal: bool = False) -> Path:
    if not value or "\x00" in value:
        raise ToolFailure("INVALID_PARAM", "Empty or invalid path")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        raise ToolFailure("PERMISSION", "Path escapes project_root")
    relative = candidate.relative_to(root)
    if not internal and ".devflow" in relative.parts:
        # Output artifacts can be read, but session/trace/config state is private.
        if len(relative.parts) < 2 or relative.parts[1] != "outputs":
            raise ToolFailure("PERMISSION", "Agent state is private")
    if any(":" in part for part in relative.parts):
        raise ToolFailure("PERMISSION", "Alternate data streams are not supported")
    return candidate


def writable_path(root: Path, value: str) -> Path:
    path = safe_path(root, value)
    parts = path.relative_to(root).parts
    if ".devflow" in parts or ".git" in parts:
        raise ToolFailure("PERMISSION", "Protected metadata directory")
    return path


def atomic_write(path: Path, content: bytes, *, overwrite: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    fd, tmp = tempfile.mkstemp(prefix=".devflow-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        if overwrite:
            os.replace(tmp, path)
        else:
            # Linking is an atomic create-if-absent, avoiding a check/replace race.
            os.link(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def check_command(command: str, allowed: bool):
    normalized = command.casefold().replace("`", "").replace("^", "")
    blocked = [
        r"\b(rm|rmdir|rd)\s+.*(-rf|-fr|/s)",
        r"\b(remove-item|del|erase)\b",
        r"\b(mkfs|format|diskpart|shutdown|reboot)\b",
        r"\bgit\s+reset\s+--hard",
        r"\bgit\s+clean\b",
        r"\bgit\s+push\b.*(--force|-f)\b",
        r"\b(curl|wget|invoke-webrequest)\b.*[|]",
        r":\s*\(\s*\)\s*\{",
        r"\b(encodedcommand|iex|invoke-expression)\b",
    ]
    if any(re.search(pattern, normalized) for pattern in blocked):
        raise ToolFailure("PERMISSION", "High-risk command blocked by policy")
    if not allowed:
        raise ToolFailure(
            "APPROVAL_REQUIRED", "Enable shell explicitly with --allow-shell or /shell on"
        )
