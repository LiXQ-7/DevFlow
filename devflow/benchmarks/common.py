import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

DATA = Path(__file__).parent / "data"


def load_data(name):
    return [
        json.loads(line) for line in (DATA / name).read_text(encoding="utf-8").splitlines() if line
    ]


def report_dir(output, name, mode):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    directory = output / f"{name}-{mode}-{stamp}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def metadata(directory, cfg=None, dataset=None, **extra):
    values = {
        "timestamp": datetime.now(UTC).isoformat(),
        "runtime_commit": "93e77ea60c13436636c9b39b6761ff8dfe940ba2",
        **extra,
    }
    if cfg:
        values.update(
            model=cfg.model,
            temperature=cfg.temperature,
            context_window=cfg.context_window,
            reserve_tokens=cfg.reserve_tokens,
        )
    if dataset:
        values["dataset_sha256"] = hashlib.sha256((DATA / dataset).read_bytes()).hexdigest()
    (directory / "metadata.json").write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_report(directory, text):
    path = directory / "report.md"
    path.write_text(text, encoding="utf-8")
    return path
