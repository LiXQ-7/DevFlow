"""Retry the pair affected by a Windows ledger sharing violation; preserve both original arms."""

import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from run_live_evaluation import context_job

from devflow.benchmarks.common import load_data

if __name__ == "__main__":
    directory = Path("benchmark-results/deepseek-live-20260915-r1").resolve()
    (directory / "infrastructure-retry.json").write_text(
        json.dumps(
            {
                "declared_at": datetime.now(UTC).isoformat(),
                "original_pair": "context-00",
                "replacement_pair": "context-00-infra-retry",
                "reason": "WinError 5 replacing budget.tmp with budget.json; cost-ledger infrastructure fault",
                "rule": "Replace both A/B arms using identical original prompts and fresh workspaces after ledger retry fix; retain originals; do not select based on task quality.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    task = load_data("context_tasks.jsonl")[0]
    task["id"] = "context-00-infra-retry"
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(context_job, task, arm, directory) for arm in ("A", "B")]
        for future in as_completed(futures):
            _, score = future.result()
            print(score, flush=True)
