#!/usr/bin/env python3
"""Harness for the three-arm anchor/structural-editing experiment.

The harness does not call an LLM.  It prepares identical run directories, scores
the artifacts produced by whatever agent ran them, and aggregates the results.
That keeps the measurement deterministic and lets the same bench be replayed
with a different model.

Commands
--------
    python bench/harness.py init [--tasks W1_retry,R1_retry_loop] [--arms A,B,C]
    python bench/harness.py score [RUN_DIR ...]
    python bench/harness.py report
    python bench/harness.py list
"""

from __future__ import annotations

import argparse
import ast
import csv
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pyforai import check_source  # noqa: E402

TASKS = {
    "W1_retry": {"kind": "write"},
    "R1_retry_loop": {"kind": "refactor"},
    "R2_reconcile": {"kind": "refactor"},
}
ARMS = {
    "A": "A_no_anchors",
    "B": "B_anchors",
    "C": "C_structural",
}
ARM_LABELS = {
    "A": "no anchors",
    "B": "anchors",
    "C": "anchors + structural editing",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_int(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _attempt_stats(path: Path) -> tuple[Optional[int], Optional[int]]:
    """Return (test runs, failed test runs) from ``attempts.log``.

    A "repair" is a test run that failed; verification runs that pass are not
    counted as repairs even if the agent logged them as separate attempts.
    """
    if not path.exists():
        return None, None
    try:
        lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return None, None
    failures = sum(1 for line in lines if re.search(r"\bfail\b", line, re.IGNORECASE))
    return len(lines), failures


def _count_pyforai(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        return sum(
            1
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if "pyforai" in line
        )
    except OSError:
        return None


def build_prompt(task: str, arm: str, run_name: str, arm_rules: str) -> str:
    rel = f"bench/runs/{run_name}"
    if TASKS[task]["kind"] == "refactor":
        kind_note = f"`{rel}/solution.py` already contains the code to refactor. Edit it in place."
    else:
        kind_note = f"`{rel}/solution.py` is empty. Implement the task there."
    return f"""# Controlled programming experiment

Work from the project root: `{ROOT}`.
Your run directory: `{rel}`.
{kind_note}

Read `{rel}/task.md` and `{rel}/tests_public.py` first.

## Goal

Make `{rel}/solution.py` pass the public tests:

```bash
(cd {rel} && python -m unittest tests_public -v)
```

## Arm rules

{arm_rules}

## Logging (required)

- At the start: `date +%s > {rel}/started_at.txt`
- After each test run, append one line to `{rel}/attempts.log`:
  `<epoch> attempt <n> <pass|fail>`
- Append every `pyforai` command you run to `{rel}/commands.log`.
- At the end: `date +%s > {rel}/finished_at.txt`

## Rules

- Do not modify `task.md` or `tests_public.py`.
- Do not read or modify other runs, `bench/tasks`, `bench/hidden`, or `bench/DESIGN.md`.
- At most 3 repair attempts.
- When done, write a 3-line summary to `{rel}/summary.md` and reply with the same summary.
"""


def cmd_init(args: argparse.Namespace) -> int:
    tasks = args.tasks.split(",") if args.tasks else list(TASKS)
    arms = args.arms.split(",") if args.arms else list(ARMS)
    for task in tasks:
        if task not in TASKS:
            raise SystemExit(f"unknown task: {task}")
        task_dir = BENCH / "tasks" / task
        if not task_dir.is_dir():
            raise SystemExit(f"missing task directory: {task_dir}")
        for arm in arms:
            if arm not in ARMS:
                raise SystemExit(f"unknown arm: {arm}")
            run_name = f"{task}__{arm}"
            run_dir = BENCH / "runs" / run_name
            if run_dir.exists():
                if not args.force:
                    print(f"skip {run_name} (exists; use --force to recreate)")
                    continue
                shutil.rmtree(run_dir)
            run_dir.mkdir(parents=True)
            shutil.copy2(task_dir / "task.md", run_dir / "task.md")
            shutil.copy2(task_dir / "tests_public.py", run_dir / "tests_public.py")
            start = task_dir / "start.py"
            if start.exists():
                shutil.copy2(start, run_dir / "start.py")
                shutil.copy2(start, run_dir / "solution.py")
            else:
                (run_dir / "solution.py").write_text("", encoding="utf-8")
            arm_rules = (BENCH / "arms" / f"{ARMS[arm]}.md").read_text(encoding="utf-8")
            arm_rules = arm_rules.replace("{run}", f"bench/runs/{run_name}")
            (run_dir / "arm.md").write_text(arm_rules, encoding="utf-8")
            (run_dir / "prompt.md").write_text(
                build_prompt(task, arm, run_name, arm_rules), encoding="utf-8"
            )
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "task": task,
                        "arm": arm,
                        "arm_name": ARMS[arm],
                        "task_kind": TASKS[task]["kind"],
                        "tests_sha256": _sha256(task_dir / "tests_public.py"),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"created {run_name}")
    return 0


def _run_unittest(run_dir: Path, module: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", module, "-v"],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    output = (proc.stdout + proc.stderr)[-4000:]
    return proc.returncode == 0, output


def score_run(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    task = meta["task"]
    arm = meta["arm"]
    solution = run_dir / "solution.py"
    metrics: dict = {
        "run": run_dir.name,
        "task": task,
        "arm": arm,
        "arm_name": meta.get("arm_name", ARMS.get(arm, arm)),
        "task_kind": meta.get("task_kind"),
        "solution_exists": solution.exists(),
        "syntax_ok": False,
        "anchor_errors": None,
        "anchor_warnings": None,
        "anchor_count": 0,
        "public_pass": False,
        "hidden_pass": False,
        "tampered_tests": False,
        "loc": 0,
        "diff_added": 0,
        "diff_removed": 0,
        "repair_attempts": None,
        "test_runs": None,
        "wall_time_s": None,
        "pyforai_calls": None,
        "summary": "",
        "check_output": "",
        "public_output": "",
        "hidden_output": "",
    }

    if solution.exists():
        text = solution.read_text(encoding="utf-8", errors="replace")
        if text.startswith("\ufeff"):
            text = text[1:]
        try:
            ast.parse(text)
            metrics["syntax_ok"] = True
        except SyntaxError:
            pass
        result = check_source(text, str(solution))
        metrics["anchor_errors"] = len(result.errors)
        metrics["anchor_warnings"] = len(result.warnings)
        if result.model is not None:
            metrics["anchor_count"] = len(result.model.anchors)
        metrics["check_output"] = "\n".join(
            f"{d.code} L{d.lineno}:C{d.col} {d.message}" for d in result.diagnostics
        )[:2000]
        metrics["loc"] = sum(1 for line in text.splitlines() if line.strip())
        start = run_dir / "start.py"
        old_lines = (
            start.read_text(encoding="utf-8", errors="replace").splitlines()
            if start.exists()
            else []
        )
        new_lines = text.splitlines()
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
        metrics["diff_added"] = sum(
            1 for line in diff if line.startswith("+") and not line.startswith("+++")
        )
        metrics["diff_removed"] = sum(
            1 for line in diff if line.startswith("-") and not line.startswith("---")
        )

    public_ok, public_output = _run_unittest(run_dir, "tests_public")
    metrics["public_pass"] = public_ok
    metrics["public_output"] = public_output

    hidden_source = BENCH / "hidden" / f"{task}.py"
    if hidden_source.exists():
        shutil.copy2(hidden_source, run_dir / "test_hidden.py")
        hidden_ok, hidden_output = _run_unittest(run_dir, "test_hidden")
        metrics["hidden_pass"] = hidden_ok
        metrics["hidden_output"] = hidden_output

    original_tests = BENCH / "tasks" / task / "tests_public.py"
    current_tests = run_dir / "tests_public.py"
    metrics["tampered_tests"] = not (
        current_tests.exists() and _sha256(current_tests) == meta.get("tests_sha256")
    )
    metrics["test_runs"], metrics["repair_attempts"] = _attempt_stats(run_dir / "attempts.log")
    metrics["pyforai_calls"] = _count_pyforai(run_dir / "commands.log")
    started = _read_int(run_dir / "started_at.txt")
    finished = _read_int(run_dir / "finished_at.txt")
    if started is not None and finished is not None and finished >= started:
        metrics["wall_time_s"] = finished - started

    summary = run_dir / "summary.md"
    if summary.exists():
        metrics["summary"] = summary.read_text(encoding="utf-8", errors="replace")[:1000]

    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return metrics


def cmd_score(args: argparse.Namespace) -> int:
    if args.runs:
        run_dirs = [Path(r) for r in args.runs]
    else:
        run_dirs = sorted(p.parent for p in (BENCH / "runs").glob("*/run.json"))
    if not run_dirs:
        raise SystemExit("no runs found; run `init` first")
    for run_dir in run_dirs:
        metrics = score_run(run_dir)
        print(
            f"{metrics['run']}: public={metrics['public_pass']} "
            f"hidden={metrics['hidden_pass']} anchors={metrics['anchor_count']} "
            f"anchor_errors={metrics['anchor_errors']} loc={metrics['loc']} "
            f"repaired={metrics['repair_attempts']} wall={metrics['wall_time_s']}"
        )
    return 0


def _mean(values: list[Optional[int | float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _fmt(value: Optional[int | float], digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _aggregate(metrics: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for arm in ("A", "B", "C"):
        group = [m for m in metrics if m["arm"] == arm]
        if not group:
            continue
        hidden = sum(1 for m in group if m["hidden_pass"])
        public = sum(1 for m in group if m["public_pass"])
        wall_values = [m["wall_time_s"] for m in group if m["wall_time_s"] is not None]
        wall_total = sum(wall_values)
        rows.append(
            {
                "arm": arm,
                "label": ARM_LABELS[arm],
                "n": len(group),
                "public": f"{public}/{len(group)}",
                "hidden": f"{hidden}/{len(group)}",
                "anchor_errors": _mean([m["anchor_errors"] for m in group]),
                "anchor_count": _mean([m["anchor_count"] for m in group]),
                "loc": _mean([m["loc"] for m in group]),
                "diff": _mean(
                    [
                        (m["diff_added"] + m["diff_removed"])
                        for m in group
                    ]
                ),
                "repair": _mean([m["repair_attempts"] for m in group]),
                "wall": _mean(wall_values),
                "wall_total": wall_total if wall_values else None,
                "success_per_min": (hidden / wall_total * 60) if wall_total else None,
                "pyforai_calls": _mean([m["pyforai_calls"] for m in group]),
                "tampered": sum(1 for m in group if m["tampered_tests"]),
            }
        )
    return rows


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def cmd_report(args: argparse.Namespace) -> int:
    metrics_files = sorted((BENCH / "runs").glob("*/metrics.json"))
    if not metrics_files:
        raise SystemExit("no metrics found; run `score` first")
    metrics = [json.loads(path.read_text(encoding="utf-8")) for path in metrics_files]

    per_run_rows = []
    for m in sorted(metrics, key=lambda x: (x["task"], x["arm"])):
        per_run_rows.append(
            [
                m["task"],
                m["arm"],
                "yes" if m["public_pass"] else "no",
                "yes" if m["hidden_pass"] else "no",
                str(m["anchor_errors"]),
                str(m["anchor_count"]),
                str(m["loc"]),
                f'{m["diff_added"]}/{m["diff_removed"]}',
                _fmt(m["repair_attempts"]),
                _fmt(m["wall_time_s"]),
                _fmt(m["pyforai_calls"]),
                "TAMPERED" if m["tampered_tests"] else "",
            ]
        )

    aggregate_rows = []
    for row in _aggregate(metrics):
        aggregate_rows.append(
            [
                row["arm"],
                row["label"],
                str(row["n"]),
                row["public"],
                row["hidden"],
                _fmt(row["anchor_errors"]),
                _fmt(row["anchor_count"]),
                _fmt(row["loc"]),
                _fmt(row["diff"]),
                _fmt(row["repair"]),
                _fmt(row["wall"]),
                _fmt(row["success_per_min"], 2),
                _fmt(row["pyforai_calls"]),
                str(row["tampered"]),
            ]
        )

    per_run = _markdown_table(
        [
            "task",
            "arm",
            "public",
            "hidden",
            "anchor err",
            "anchors",
            "LOC",
            "diff +/-",
            "repair",
            "wall s",
            "pyforai",
            "flags",
        ],
        per_run_rows,
    )
    aggregate = _markdown_table(
        [
            "arm",
            "condition",
            "n",
            "public",
            "hidden",
            "anchor err",
            "anchors",
            "LOC",
            "diff",
            "repair",
            "wall s",
            "success/min",
            "pyforai",
            "tampered",
        ],
        aggregate_rows,
    )

    report = f"""# Pilot results

Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}

> **This is a pilot with one run per task×arm cell.** It is a smoke test of the
> measurement pipeline and a source of effect-size hints, not a powered study.
> Do not read p-values or confidence intervals into these numbers.

## Per run

{per_run}

## Aggregate by arm

{aggregate}

`success/min` is `hidden passes / total wall-clock minutes` for runs that
reported `started_at.txt` and `finished_at.txt`. `diff +/-` is added/removed
lines against `start.py` (for write tasks, against an empty file).
`anchor err` is the number of `pyforai check` errors in the final artifact.

## Caveats

- N=1 per cell; task difficulty and model stochasticity dominate.
- Runs share the same underlying model; only the workflow instructions/tools differ.
- `wall s` and `repair` are self-reported by the agent through timestamp/log files.
- Hidden tests are copied into the run directory only after the agent finishes.
- A tampered `tests_public.py` is flagged but not automatically excluded.
"""
    (BENCH / "report.md").write_text(report, encoding="utf-8")
    print(report)

    csv_path = BENCH / "report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metrics[0].keys()))
        writer.writeheader()
        for m in metrics:
            writer.writerow(m)
    print(f"\nwrote {csv_path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for path in sorted((BENCH / "runs").glob("*/run.json")):
        run_dir = path.parent
        metrics_path = run_dir / "metrics.json"
        status = "unscored"
        if metrics_path.exists():
            m = json.loads(metrics_path.read_text(encoding="utf-8"))
            status = f"public={m['public_pass']} hidden={m['hidden_pass']}"
        print(f"{run_dir.name}: {status}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create run directories and prompts")
    init.add_argument("--tasks", help="comma-separated task ids")
    init.add_argument("--arms", help="comma-separated arm ids (A,B,C)")
    init.add_argument("--force", action="store_true", help="recreate existing runs")
    init.set_defaults(func=cmd_init)

    score = sub.add_parser("score", help="score run artifacts")
    score.add_argument("runs", nargs="*", help="run directories; default: all")
    score.set_defaults(func=cmd_score)

    report = sub.add_parser("report", help="aggregate metrics into report.md")
    report.set_defaults(func=cmd_report)

    list_parser = sub.add_parser("list", help="list runs")
    list_parser.set_defaults(func=cmd_list)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
