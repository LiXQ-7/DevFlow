import json
import re
from datetime import UTC, datetime

from filelock import FileLock

SENSITIVE = re.compile(r"api.?key|authorization|cookie|token|secret|password|密码", re.I)


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if SENSITIVE.search(k)
                and not k.endswith(("tokens", "_tokens", "_tokens_before", "_tokens_after"))
                else redact(v, secrets)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
        value = re.sub(
            r"(?i)((?:api[_-]?key|password|secret|token)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", value
        )
    return value


class TraceLogger:
    def __init__(self, path, session_id, secrets=()):
        self.path, self.session_id, self.secrets = path, session_id, secrets
        path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event, data=None, branch_id=None):
        record = {
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": self.session_id,
            "branch_id": branch_id,
            **redact(data or {}, self.secrets),
        }
        with FileLock(str(self.path) + ".lock"), self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def records(self):
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
