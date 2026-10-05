import json

from pydantic import BaseModel, Field


class CodingSummary(BaseModel):
    Goal: str = ""
    Constraints: list[str] = Field(default_factory=list)
    Done: list[str] = Field(default_factory=list)
    InProgress: list[str] = Field(default_factory=list)
    FailedAttempts: list[str] = Field(default_factory=list)
    FilesRead: list[dict] = Field(default_factory=list)
    FilesModified: list[dict] = Field(default_factory=list)
    CurrentTODO: list[dict] = Field(default_factory=list)
    NextSteps: list[str] = Field(default_factory=list)

    def absorb(self, messages):
        """Extractive deterministic summary: keep user requirements verbatim, not LLM guesses."""
        calls = {}
        for message in messages:
            content = message.get("content") or ""
            if message["role"] == "user":
                if not self.Goal:
                    self.Goal = content
                if content not in self.Constraints:
                    self.Constraints.append(content)
            for call in message.get("tool_calls", []):
                calls[call["id"]] = call["function"]
            if message["role"] == "tool":
                try:
                    result = json.loads(content)
                    function = calls.get(message.get("tool_call_id"), {})
                    name = function.get("name", "")
                    data = result.get("data", {})
                    if result.get("status") == "ERROR":
                        self.FailedAttempts.append(
                            f"{name}: {result.get('error_code')}: {result.get('text')}"
                        )
                    elif name == "Read":
                        self.FilesRead.append(
                            {k: data.get(k) for k in ("path", "sha256", "start_line", "end_line")}
                        )
                    elif name in ("Write", "Edit"):
                        self.FilesModified.append(
                            {k: data.get(k) for k in ("path", "sha256", "new_hash")}
                        )
                    elif name == "TodoWrite":
                        self.CurrentTODO = data.get("todos", [])
                except (json.JSONDecodeError, AttributeError, TypeError):
                    self.FailedAttempts.append("Unstructured tool result: " + content[:400])
            elif message["role"] == "assistant" and content and not message.get("tool_calls"):
                self.Done.append(content[:1500])
        self.InProgress = [t["content"] for t in self.CurrentTODO if t["status"] == "in_progress"]
        self.NextSteps = [t["content"] for t in self.CurrentTODO if t["status"] == "pending"]
        # Dedup exact repeated evidence without erasing different hashes/line ranges.
        for field in ("FilesRead", "FilesModified", "FailedAttempts", "Done"):
            unique = {
                json.dumps(x, sort_keys=True, ensure_ascii=False): x for x in getattr(self, field)
            }
            setattr(self, field, list(unique.values()))
        return self
