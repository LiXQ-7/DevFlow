import copy
import json
from uuid import uuid4

from .jsonl_store import JsonlStore
from .models import SessionEntry


class SessionManager:
    def __init__(self, directory, session_id=None, project_root=None, create=True):
        self.session_id = session_id or uuid4().hex
        self.store = JsonlStore(directory, self.session_id)
        self.entries = self.store.load()
        self.leaf_id = self.entries[-1].id if self.entries else None
        if not self.entries:
            if not create:
                raise FileNotFoundError(f"Session {self.session_id} does not exist")
            self.append("session_meta", {"project_root": str(project_root), "version": 1})
        elif project_root and self.entries[0].payload.get("project_root") != str(project_root):
            raise ValueError("Session belongs to a different project_root")

    def append(self, type, payload, parent_id=None):
        parent = self.leaf_id if parent_id is None else parent_id
        entry = SessionEntry(
            parent_id=parent, session_id=self.session_id, type=type, payload=copy.deepcopy(payload)
        )
        self.store.append(entry, self.entries[-1].id if self.entries else None)
        self.entries.append(entry)
        self.leaf_id = entry.id
        return entry

    def active_branch(self, leaf_id=None):
        by_id = {entry.id: entry for entry in self.entries}
        current = leaf_id or self.leaf_id
        chain, visited = [], set()
        while current is not None:
            if current in visited or current not in by_id:
                raise ValueError("Invalid branch")
            visited.add(current)
            node = by_id[current]
            chain.append(node)
            current = node.parent_id
        return list(reversed(chain))

    def branch(self, entry_id):
        # Explicit event makes the active branch recoverable without a mutable HEAD sidecar.
        self.active_branch(entry_id)
        return self.append(
            "branch_summary",
            {
                "source_entry_id": entry_id,
                "note": "Conversation branch only; working files have not been rolled back. Verify hashes before editing.",
            },
            parent_id=entry_id,
        )

    def record_message(self, message):
        role = message["role"]
        kind = {"user": "user_message", "assistant": "assistant_message", "tool": "tool_result"}[
            role
        ]
        return self.append(kind, {"message": message})

    def messages(self):
        result = []
        for entry in self.active_branch():
            if entry.type == "compaction":
                result = copy.deepcopy(entry.payload["messages"])
            elif "message" in entry.payload:
                result.append(copy.deepcopy(entry.payload["message"]))
            # Branch notes stay in metadata: a system message inserted between an
            # assistant call and its recovered tool result would violate the API protocol.
        return result

    def todo_snapshot(self):
        snapshot = {"summary": "", "todos": []}
        for entry in self.active_branch():
            if entry.type == "todo_snapshot":
                snapshot = entry.payload
            if entry.type == "tool_result":
                try:
                    result = json.loads(entry.payload["message"]["content"])
                    if result.get("status") != "ERROR" and "todos" in result.get("data", {}):
                        snapshot = {k: result["data"][k] for k in ("summary", "todos")}
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
        return copy.deepcopy(snapshot)

    def pending_calls(self):
        pending = {}
        for message in self.messages():
            for call in message.get("tool_calls", []):
                pending[call["id"]] = call
            if message["role"] == "tool":
                pending.pop(message.get("tool_call_id"), None)
        return pending

    def recover_pending(self):
        """Never replay a tool automatically. Mark unknown outcomes and close protocol pairs."""
        pending = self.pending_calls()
        for call_id, call in pending.items():
            result = {
                "status": "ERROR",
                "error_code": "INTERRUPTED_UNKNOWN_OUTCOME",
                "text": "Interrupted before durable result. Do not retry automatically. Verify files, hashes, git diff or process state first.",
                "data": {"tool": call["function"]["name"], "side_effect_uncertain": True},
            }
            self.record_message(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        if pending:
            self.append("recovery", {"pending_call_ids": list(pending), "auto_replayed": False})
        return pending

    def compact(self, data):
        kept = data.pop("first_kept_message", None)
        data["first_kept_entry_id"] = next(
            (e.id for e in self.active_branch() if e.payload.get("message") == kept), None
        )
        return self.append("compaction", data)

    @staticmethod
    def list_sessions(directory):
        return (
            sorted(directory.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
            if directory.exists()
            else []
        )
