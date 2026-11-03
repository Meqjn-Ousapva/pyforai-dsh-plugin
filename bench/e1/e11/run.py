"""E1.1: single-function repair tasks, no twin oracle.

The E1 repair pilot hit a ceiling: `process` and `audit` were near-identical,
so a control agent could diff the two functions to localise a drift.  E1.1
removes the twin, keeps only `process`, and compares three ways of getting the
diagnostic:

``no_check``
    no pyforai; debug from the public tests and the anchors.
``tool_check``
    the agent runs ``pyforai check`` itself before editing.
``forced_diagnostic``
    the harness runs check on the drifted start file and writes the exact
    diagnostic to ``diagnostics.md``; the agent is told to read it first.  This
    separates the value of the diagnostic from the ability to invoke the tool.

All tasks are **silent**: the public tests pass, the hidden tests fail, and the
drift is in a branch the public examples do not exercise.  The source is a
single `process` function with 32 record kinds; there is no `audit` twin.

Usage::

    python -m bench.e1.e11.run build
    python -m bench.e1.e11.run init --arms no_check,tool_check,forced_diagnostic
    python -m bench.e1.e11.run score
    python -m bench.e1.e11.run report
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from ..common import (
    E1,
    anchor_fingerprint,
    check_path_cli,
    count_check_calls,
    count_log_failures,
    edit_payload_bytes,
    parse_epoch,
    read_json,
    sha256_file,
    sha256_text,
    write_json,
    write_text,
)
from ..drift import InjectionError, else_drift_targets, make_case
from ..repair import hidden_fails, public_fails, run_unittest

E11 = E1 / "e11"
SOURCES = E11 / "sources"
TASKS = E11 / "tasks"
RUNS = E11 / "runs"
RESULTS = E11 / "results"
ARMS = ("no_check", "tool_check", "forced_diagnostic")
HIDDEN_NAME = "test_hidden.py"


# ---------------------------------------------------------------------------
# build


def task_md(index: int) -> str:
    return f"""# E1.1 repair task {index:02d}: single-function silent drift

`solution.py` is a working single-function module.  A previous edit introduced a
**structural drift** in one branch: the code still parses, the public tests
still pass, but the hidden tests fail.

The `# end ...` anchors describe the intended block structure from before the
edit.  They are assertions, not decoration.

Your job is to restore the intended behaviour.

Rules:

- Edit `solution.py` in place.
- Do **not** modify `task.md` or `tests_public.py`.
- Do **not** modify, add, or remove any `# end ...` anchor.
- At most 3 repair attempts (a repair attempt is a test run that fails).
- The drift is local.  Do not rewrite the whole function.
"""


def cmd_build(args: argparse.Namespace) -> int:
    reference = (SOURCES / "reference.py").read_text(encoding="utf-8")
    tests = (SOURCES / "tests_public.py").read_text(encoding="utf-8")
    hidden = (SOURCES / "hidden.py").read_text(encoding="utf-8")
    candidates = []
    for target in else_drift_targets(reference, "e11", per_file=100):
        try:
            case = make_case(reference, target, "hoist_else")
        except InjectionError:
            continue
        public_failed, public_output = public_fails(case.source, tests)
        if public_failed:
            continue
        hidden_failed, hidden_output = hidden_fails(case.source, tests, hidden)
        if not hidden_failed:
            continue
        candidates.append((target, case, hidden_output))
        if len(candidates) >= args.tasks:
            break
    if len(candidates) < args.tasks:
        raise SystemExit(f"only found {len(candidates)} usable candidates")
    if TASKS.exists() and args.force:
        shutil.rmtree(TASKS)
    TASKS.mkdir(parents=True, exist_ok=True)
    for index, (target, case, hidden_output) in enumerate(candidates, 1):
        slug = f"E11_{index:02d}_L{target.lineno}"
        directory = TASKS / slug
        directory.mkdir(parents=True, exist_ok=True)
        write_text(directory / "start.py", case.source)
        write_text(directory / "expected.py", reference)
        write_text(directory / "tests_public.py", tests)
        write_text(directory / "hidden.py", hidden)
        write_text(directory / "task.md", task_md(index))
        write_json(
            directory / "meta.json",
            {
                "slug": slug,
                "target": {
                    "kind": target.kind,
                    "lineno": target.lineno,
                    "end_lineno": target.end_lineno,
                    "col": target.col,
                },
                "anchor_line": case.anchor_line,
                "drift_line": case.drift_line,
                "expected_codes": list(case.expected_codes),
                "tests_sha256": sha256_text(tests),
                "start_sha256": sha256_text(case.source),
                "hidden_failure": hidden_output[-800:],
            },
        )
        print(f"built {slug}")
    return 0


# ---------------------------------------------------------------------------
# init


def arm_text(arm: str, run_rel: str) -> str:
    if arm == "no_check":
        return f"""# Arm: no_check

- Do **not** run `pyforai` or any structural checker.
- Debug from the public tests, the anchors, and the code.
- The public tests pass; the hidden tests fail.  The anchors are the only
  structural clue.
"""
    if arm == "tool_check":
        return f"""# Arm: tool_check

- Before editing, run:

  ```bash
  pyforai check {run_rel}/solution.py
  ```

  The diagnostic names the anchor line and the block it belongs to.
- After each edit, run `check` again and fix every anchor error.
- Do not modify the anchors; if check reports a mismatch, the code moved.
"""
    if arm == "forced_diagnostic":
        return f"""# Arm: forced_diagnostic

- The harness has already run `pyforai check` on the drifted start file.  Read
  `{run_rel}/diagnostics.md` **before** inspecting the code.
- Do **not** run `pyforai` yourself in this arm.  The diagnostic in
  `diagnostics.md` is the treatment; extra calls would make this arm the same
  as `tool_check`.
- Do not modify the anchors.
"""
    raise SystemExit(f"unknown arm: {arm}")


def build_prompt(arm: str, run_name: str) -> str:
    run_rel = f"bench/e1/e11/runs/{run_name}"
    return f"""# Controlled repair experiment (E1.1)

Work from the project root: `{os.getcwd()}`.
Your run directory: `{run_rel}`.

`solution.py` is a single-function module with a structural drift.  The public
tests pass; the hidden tests fail.  The drift is in a branch the public examples
do not exercise.

Read `{run_rel}/task.md` and `{run_rel}/tests_public.py` first.

## Goal

Make `{run_rel}/solution.py` pass the hidden tests.  The hidden tests are used
for scoring and are not visible.  Do not try to read `bench/e1/e11/sources`,
`bench/e1/e11/tasks`, or another run.

## Arm rules

{arm_text(arm, run_rel)}

## Logging (required)

- At the start: `date +%s > {run_rel}/started_at.txt`
- After each edit:

  ```bash
  mkdir -p {run_rel}/edits
  cp {run_rel}/solution.py {run_rel}/edits/$(date +%s)_after.py
  echo '{{"ts": '$(date +%s)', "file": "solution.py"}}' >> {run_rel}/edits.jsonl
  ```

- After each test run, append one line to `{run_rel}/attempts.log`:
  `<epoch> attempt <n> <pass|fail>`
- Append every command that touches `pyforai` to `{run_rel}/commands.log`.
- If your runtime reports token usage, write `{run_rel}/usage.json` as
  `{{"input_tokens": <n>, "output_tokens": <n>}}`.
- At the end: `date +%s > {run_rel}/finished_at.txt`

## Rules

- Do not modify `task.md`, `tests_public.py`, or any `# end ...` anchor.
- At most 3 repair attempts.
- When done, write a 3-line summary to `{run_rel}/summary.md` and reply with the
  same summary.
"""


def forced_diagnostic(start: Path) -> str:
    result = check_path_cli(start)
    lines = ["pyforai check solution.py", ""]
    if not result["diagnostics"]:
        lines.append("(no diagnostics)")
    for diagnostic in result["diagnostics"]:
        lines.append(
            f"{diagnostic.get('code')} L{diagnostic.get('line')}:C{diagnostic.get('col')} "
            f"{diagnostic.get('message')}"
        )
    return "\n".join(lines) + "\n"


def cmd_init(args: argparse.Namespace) -> int:
    arms = args.arms.split(",") if args.arms else list(ARMS)
    tasks = args.tasks.split(",") if args.tasks else sorted(p.name for p in TASKS.iterdir() if p.is_dir())
    if not tasks:
        raise SystemExit("no tasks; run `build` first")
    reps = max(1, args.reps)
    for task in tasks:
        task_dir = TASKS / task
        if not task_dir.is_dir():
            raise SystemExit(f"missing task: {task_dir}")
        meta = read_json(task_dir / "meta.json")
        for arm in arms:
            if arm not in ARMS:
                raise SystemExit(f"unknown arm: {arm}")
            for rep in range(1, reps + 1):
                run_name = f"{task}__{arm}" if reps == 1 else f"{task}__{arm}__r{rep}"
                run_dir = RUNS / run_name
                if run_dir.exists():
                    if not args.force:
                        print(f"skip {run_name} (exists)")
                        continue
                    shutil.rmtree(run_dir)
                run_dir.mkdir(parents=True)
                (run_dir / "edits").mkdir()
                for name in ("task.md", "tests_public.py", "start.py"):
                    shutil.copy2(task_dir / name, run_dir / name)
                shutil.copy2(task_dir / "start.py", run_dir / "solution.py")
                write_text(run_dir / "arm.md", arm_text(arm, f"bench/e1/e11/runs/{run_name}"))
                write_text(run_dir / "prompt.md", build_prompt(arm, run_name))
                if arm == "forced_diagnostic":
                    write_text(run_dir / "diagnostics.md", forced_diagnostic(run_dir / "solution.py"))
                write_json(
                    run_dir / "run.json",
                    {
                        "task": task,
                        "arm": arm,
                        "rep": rep,
                        "tests_sha256": meta["tests_sha256"],
                        "start_sha256": meta["start_sha256"],
                        "anchor_line": meta["anchor_line"],
                        "drift_line": meta["drift_line"],
                    },
                )
                print(f"created {run_name}")
    return 0


# ---------------------------------------------------------------------------
# score


def _first_edit_seconds(run_dir: Path) -> Optional[int]:
    started = parse_epoch(run_dir / "started_at.txt")
    if started is None:
        return None
    timestamps: list[int] = []
    log = run_dir / "edits.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line).get("ts")
                if isinstance(value, int):
                    timestamps.append(value)
            except (json.JSONDecodeError, AttributeError):
                continue
    if not timestamps:
        for path in (run_dir / "edits").glob("*_after.py"):
            timestamps.append(int(path.stat().st_mtime))
    if not timestamps:
        return None
    return max(0, min(timestamps) - started)


def _edits_metrics(run_dir: Path) -> dict:
    edits = sorted((run_dir / "edits").glob("*_after.py"))
    snapshots: list[str] = []
    start = run_dir / "start.py"
    if start.exists():
        snapshots.append(start.read_text(encoding="utf-8", errors="replace"))
    for edit in edits:
        snapshots.append(edit.read_text(encoding="utf-8", errors="replace"))
    solution = run_dir / "solution.py"
    if solution.exists():
        final = solution.read_text(encoding="utf-8", errors="replace")
        if not snapshots or snapshots[-1] != final:
            snapshots.append(final)
    payload = sum(edit_payload_bytes(old, new) for old, new in zip(snapshots, snapshots[1:]))
    return {"edits_count": max(0, len(snapshots) - 1), "edit_payload_bytes": payload}


def score_run(run_dir: Path) -> dict:
    meta = read_json(run_dir / "run.json")
    task = meta["task"]
    arm = meta["arm"]
    solution_path = run_dir / "solution.py"
    solution = solution_path.read_text(encoding="utf-8", errors="replace") if solution_path.exists() else ""
    start = (run_dir / "start.py").read_text(encoding="utf-8", errors="replace") if (run_dir / "start.py").exists() else ""
    metrics = {
        "run": run_dir.name,
        "task": task,
        "arm": arm,
        "rep": meta.get("rep", 1),
        "solution_exists": solution_path.exists(),
        "syntax_ok": False,
        "public_pass": False,
        "hidden_pass": False,
        "solved": False,
        "first_try": False,
        "anchors_modified": False,
        "anchor_errors": None,
        "anchor_errors_start": None,
        "check_calls": 0,
        "pyforai_calls": 0,
        "test_runs": None,
        "failures": None,
        "time_to_first_edit_s": None,
        "wall_time_s": None,
        "edits_count": 0,
        "edit_payload_bytes": 0,
        "usage": None,
        "diagnostic_available": (run_dir / "diagnostics.md").exists(),
        "arm_compliance": None,
        "summary": "",
    }
    if solution:
        try:
            ast.parse(solution)
            metrics["syntax_ok"] = True
        except SyntaxError:
            pass
        result = check_path_cli(solution_path)
        metrics["anchor_errors"] = len([d for d in result["diagnostics"] if d.get("code") != "E010"])
        start_result = check_path_cli(run_dir / "start.py") if start else None
        metrics["anchor_errors_start"] = (
            len([d for d in start_result["diagnostics"] if d.get("code") != "E010"]) if start_result else None
        )
        metrics["anchors_modified"] = anchor_fingerprint(start) != anchor_fingerprint(solution)

    public_ok, _ = run_unittest(run_dir, "tests_public")
    metrics["public_pass"] = public_ok
    hidden_source = TASKS / task / "hidden.py"
    if hidden_source.exists():
        shutil.copy2(hidden_source, run_dir / HIDDEN_NAME)
        hidden_ok, _ = run_unittest(run_dir, "test_hidden")
        metrics["hidden_pass"] = hidden_ok

    metrics["check_calls"], metrics["pyforai_calls"], _ = count_check_calls(run_dir / "commands.log")
    metrics["test_runs"], metrics["failures"] = count_log_failures(run_dir / "attempts.log")
    metrics["time_to_first_edit_s"] = _first_edit_seconds(run_dir)
    started = parse_epoch(run_dir / "started_at.txt")
    finished = parse_epoch(run_dir / "finished_at.txt")
    if started is not None and finished is not None and finished >= started:
        metrics["wall_time_s"] = finished - started
    metrics.update(_edits_metrics(run_dir))
    usage = read_json(run_dir / "usage.json")
    if isinstance(usage, dict):
        metrics["usage"] = usage
    metrics["solved"] = (
        metrics["public_pass"]
        and metrics["hidden_pass"]
        and not metrics["anchors_modified"]
        and metrics["anchor_errors"] == 0
    )
    metrics["first_try"] = bool(metrics["solved"] and (metrics["failures"] or 0) == 0)
    if arm == "no_check":
        metrics["arm_compliance"] = metrics["check_calls"] == 0
    elif arm == "tool_check":
        metrics["arm_compliance"] = metrics["check_calls"] > 0
    else:
        metrics["arm_compliance"] = True
    summary = run_dir / "summary.md"
    if summary.exists():
        metrics["summary"] = summary.read_text(encoding="utf-8", errors="replace")[:1000]
    write_json(run_dir / "metrics.json", metrics)
    return metrics


def cmd_score(args: argparse.Namespace) -> int:
    run_dirs = [Path(p) for p in args.runs] if args.runs else sorted(p.parent for p in RUNS.glob("*/run.json"))
    if not run_dirs:
        raise SystemExit("no runs; run `init` first")
    for run_dir in run_dirs:
        m = score_run(run_dir)
        print(
            f"{m['run']}: solved={m['solved']} public={m['public_pass']} hidden={m['hidden_pass']} "
            f"checks={m['check_calls']} first_edit={m['time_to_first_edit_s']}s wall={m['wall_time_s']}s"
        )
    return 0


# ---------------------------------------------------------------------------
# report


def _mean(values: list[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _fmt(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def cmd_report(args: argparse.Namespace) -> int:
    files = sorted(RUNS.glob("*/metrics.json"))
    if files:
        metrics = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    else:
        archive = RESULTS / "metrics.jsonl"
        if not archive.exists():
            raise SystemExit("no metrics; run `score` first")
        metrics = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line.strip()]
    headers = ["task", "arm", "solved", "first try", "first edit s", "wall s", "payload B", "check calls", "anchors moved", "compliance"]
    rows = []
    for m in sorted(metrics, key=lambda x: (x["task"], x["arm"])):
        rows.append(
            [
                m["task"],
                m["arm"],
                "yes" if m["solved"] else "no",
                "yes" if m["first_try"] else "no",
                _fmt(m["time_to_first_edit_s"]),
                _fmt(m["wall_time_s"]),
                str(m["edit_payload_bytes"]),
                str(m["check_calls"]),
                "YES" if m["anchors_modified"] else "no",
                "yes" if m["arm_compliance"] else "NO",
            ]
        )
    aggregates = []
    for arm in ARMS:
        group = [m for m in metrics if m["arm"] == arm]
        if not group:
            continue
        aggregates.append(
            [
                arm,
                str(len(group)),
                f"{sum(1 for m in group if m['solved'])}/{len(group)}",
                f"{sum(1 for m in group if m['first_try'])}/{len(group)}",
                _fmt(_mean([m["time_to_first_edit_s"] for m in group])),
                _fmt(_mean([m["wall_time_s"] for m in group])),
                _fmt(_mean([m["edit_payload_bytes"] for m in group])),
                f"{sum(1 for m in group if m['check_calls'] > 0)}/{len(group)}",
                str(sum(1 for m in group if m["anchors_modified"])),
            ]
        )
    table = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
    table += "\n".join("| " + " | ".join(row) + " |" for row in rows)
    agg_headers = ["arm", "n", "solved", "first try", "mean first edit s", "mean wall s", "mean payload B", "check used", "anchors moved"]
    agg = "| " + " | ".join(agg_headers) + " |\n|" + "|".join("---" for _ in agg_headers) + "|\n"
    agg += "\n".join("| " + " | ".join(row) + " |" for row in aggregates)
    report = f"""# E1.1 repair report

Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}

> Small pilot.  Single-function source (no `audit` twin), silent drift,
> public tests green / hidden tests red.  N is small; treat differences as
> hypotheses.

## Per run

{table}

## Aggregate

{agg}

``first try`` = solved with no failed test run.
``first edit s`` = first snapshot timestamp minus `started_at.txt`.
``payload B`` = added/removed bytes across per-edit snapshots; a proxy for
output tokens, not a token count.

## Caveats

- Token usage is not available from the runner; `payload B` and wall time are
  proxies.
- `forced_diagnostic` gets the check output for free; `tool_check` must invoke
  the tool.  The difference is diagnostic delivery, not just model ability.
- `no_check` compliance is prompt-level.
"""
    RESULTS.mkdir(parents=True, exist_ok=True)
    write_text(RESULTS / "report.md", report)
    (RESULTS / "metrics.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in metrics) + "\n", encoding="utf-8"
    )
    print(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build tasks from the single-function source")
    build.add_argument("--tasks", type=int, default=4)
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=cmd_build)
    init = sub.add_parser("init", help="create run directories")
    init.add_argument("--tasks", help="comma-separated task slugs")
    init.add_argument("--arms", default=",".join(ARMS))
    init.add_argument("--reps", type=int, default=1)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)
    score = sub.add_parser("score", help="score runs")
    score.add_argument("runs", nargs="*")
    score.set_defaults(func=cmd_score)
    report = sub.add_parser("report", help="aggregate")
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
