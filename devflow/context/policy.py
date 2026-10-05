import copy
import json
from pathlib import Path

from devflow.runtime.hello_agents_adapter import (
    context_components,
    count_message_payloads,
    history_round_starts,
)

from .summary import CodingSummary


class ContextBudgetExceeded(RuntimeError):
    pass


class CodingContextPolicy:
    def __init__(self, config):
        self.cfg = config
        self.counter, self.truncator = context_components(
            config.model,
            config.state_dir / "outputs",
            config.output_max_lines,
            config.output_max_bytes,
            "head_tail",
        )

    def count(self, messages, schemas=()):
        # Include tool schemas, roles and call arguments, not just visible text.
        count = count_message_payloads(self.counter, messages, schemas)
        # Upstream fallback len/4 underestimates Chinese; UTF-8 bytes is conservative.
        if self.counter._encoding is None:
            serialized = json.dumps({"messages": messages, "tools": schemas}, ensure_ascii=False)
            count = len(serialized.encode("utf-8"))
        return count + 8 * len(messages)

    def truncate(self, name, result):
        result = result.model_copy(deep=True)
        self.truncator.truncate_direction = {"Read": "head", "Grep": "head", "Bash": "tail"}.get(
            name, "head_tail"
        )
        serialized = result.model_dump_json()
        # Count real observation lines, not JSON-escaped \n characters.
        truncated = self.truncator.truncate(name, result.text)
        if (
            not truncated["truncated"]
            and len(serialized.encode("utf-8")) <= self.cfg.output_max_bytes
        ):
            return result
        # Preserve the entire structured response too, including oversized data fields.
        full_output = self.truncator._save_full_output(name, serialized)
        raw = truncated["preview"].encode("utf-8")
        limit = self.cfg.output_max_bytes
        if len(raw) > limit:
            direction = self.truncator.truncate_direction
            raw = (
                raw[-limit:]
                if direction == "tail"
                else raw[:limit]
                if direction == "head"
                else (raw[: limit // 2] + b"\n...\n" + raw[-limit // 2 :])
            )
        result.text = raw.decode("utf-8", errors="ignore")
        # Never retain the full structured payload alongside a truncated preview.
        metadata = {
            k: v
            for k, v in result.data.items()
            if k
            in {
                "path",
                "sha256",
                "new_hash",
                "exit_code",
                "start_line",
                "end_line",
                "next_start_line",
                "full_stderr_path",
                "total_seen",
                "returned",
            }
        }
        result.data = {
            **metadata,
            "truncated": True,
            "full_output_path": str(Path(full_output).relative_to(self.cfg.project_root)),
        }
        if result.status == "SUCCESS":
            result.status = "PARTIAL"
        result.stats.update(truncated["stats"])
        return result

    def compact(self, messages, schemas=(), force=False):
        before = self.count(messages, schemas)
        budget = self.cfg.context_window - self.cfg.reserve_tokens
        if not force and before <= budget:
            return messages, None
        system = [
            m
            for m in messages
            if m["role"] == "system" and not m.get("content", "").startswith("DEVFLOW_SUMMARY\n")
        ]
        history = [m for m in messages if m["role"] != "system"]
        summary = CodingSummary()
        for message in messages:
            if message["role"] == "system" and message.get("content", "").startswith(
                "DEVFLOW_SUMMARY\n"
            ):
                summary = CodingSummary.model_validate_json(message["content"].split("\n", 1)[1])
        starts = history_round_starts(history)
        if len(starts) < 2:
            if before > budget:
                raise ContextBudgetExceeded(
                    "Current turn exceeds context budget; narrow input or increase window"
                )
            return messages, None
        retain = min(self.cfg.keep_recent_rounds, len(starts) - 1)
        while retain >= 1:
            cut = starts[-retain]
            candidate_summary = summary.model_copy(deep=True).absorb(history[:cut])
            summary_message = {
                "role": "system",
                "content": "DEVFLOW_SUMMARY\n" + candidate_summary.model_dump_json(),
            }
            candidate = system + [summary_message] + copy.deepcopy(history[cut:])
            after = self.count(candidate, schemas)
            if after <= budget:
                if after >= before and not force:
                    return messages, None
                return candidate, {
                    "summary": candidate_summary.model_dump(),
                    "tokens_before": before,
                    "tokens_after": after,
                    "retained_rounds": retain,
                    "messages": candidate,
                    "read_files": candidate_summary.FilesRead,
                    "modified_files": candidate_summary.FilesModified,
                    "first_kept_message": history[cut],
                }
            retain -= 1
        raise ContextBudgetExceeded(
            "Preserved requirements and latest turn exceed budget; increase context window"
        )
