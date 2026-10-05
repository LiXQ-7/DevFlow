"""Copy compact, non-secret benchmark evidence into the reviewable repository docs."""

import shutil
from pathlib import Path

from devflow.benchmarks.report import latest, run


def main():
    source = Path("benchmark-results")
    target = Path("docs/evidence")
    target.mkdir(parents=True, exist_ok=True)
    for prefix, files in {
        "tool-offline": ["tool_calling.csv"],
        "context-offline": ["context_ab.csv", "state_scores.csv"],
        "recovery-process": ["fault_injection.csv"],
    }.items():
        directory = latest(source, prefix)
        if directory is None:
            continue
        destination = target / prefix
        destination.mkdir(exist_ok=True)
        for name in ["report.md", "metadata.json", *files]:
            shutil.copyfile(directory / name, destination / name)
    shutil.copyfile(run(source), target / "report.md")
    print(target.resolve())


if __name__ == "__main__":
    main()
