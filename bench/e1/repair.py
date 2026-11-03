"""E1 repair tasks: can an agent restore a structurally drifted file?

The deterministic drift suite shows the checker *can* see injected drift.  This
module asks the behavioural question: when an agent is given a file whose block
structure has drifted, does having ``check`` help it repair the file?

Task construction starts from the old calibration references (known-correct
solutions to the T-family refactor tasks), injects a behaviour-changing dedent,
and keeps the case only if

* the file still parses,
* ``pyforai check`` reports a structural error,
* the public tests fail (so the agent has a signal), and
* the hidden tests fail (so the case is not trivially already solved).

Arms
----
``check_on``
    The prompt tells the agent to run ``pyforai check solution.py``
    before and after editing.  The checker's diagnostic names the line.
``check_off``
    The prompt forbids ``pyforai``.  The agent must debug from tests and code.

Both arms see the same anchors and the same tests.  The anchors are assertions:
the prompt says not to edit them, and the score records whether they changed.

Usage::

    python -m bench.e1.repair build --tasks T1_pipeline,T4_pipeline,T8_pipeline
    python -m bench.e1.repair init --arms check_on,check_off --reps 1
    python -m bench.e1.repair score
    python -m bench.e1.repair report
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .common import (
    BENCH,
    E1,
    ROOT,
    anchor_fingerprint,
    ast_fingerprint,
    check_path_cli,
    check_source,
    compile_ok,
    copy_task_file,
    count_check_calls,
    count_log_failures,
    diagnostic_codes,
    edit_payload_bytes,
    parse_epoch,
    read_json,
    relative,
    sha256_file,
    sha256_text,
    write_json,
    write_text,
)
from .drift import DRIFTS, InjectionError, code_drift_targets, else_drift_targets, make_case

SOURCES = E1 / "repair" / "sources"
TASKS = SOURCES / "tasks"
HIDDEN = SOURCES / "hidden"
REFERENCE = SOURCES / "reference"
REPAIR = E1 / "repair"
TASK_DIR = REPAIR / "tasks"
RUNS = REPAIR / "runs"
ARMS = REPAIR / "arms"
RESULTS = REPAIR / "results"

ARM_NAMES = ("check_on", "check_off")
PREFERRED_FUNCTIONS = ("process", "audit", "reconcile", "get", "__init__")
HIDDEN_NAME = "test_hidden.py"


# ---------------------------------------------------------------------------
# test execution


def run_unittest(directory: Path, module: str, timeout: int = 120) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", module, "-v"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-4000:]


def public_fails(source: str, tests: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="e1-repair-") as tmp:
        directory = Path(tmp)
        (directory / "solution.py").write_text(source, encoding="utf-8")
        (directory / "tests_public.py").write_text(tests, encoding="utf-8")
        ok, output = run_unittest(directory, "tests_public")
        return not ok, output


def hidden_fails(source: str, tests: str, hidden: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="e1-repair-") as tmp:
        directory = Path(tmp)
        (directory / "solution.py").write_text(source, encoding="utf-8")
        (directory / "tests_public.py").write_text(tests, encoding="utf-8")
        (directory / HIDDEN_NAME).write_text(hidden, encoding="utf-8")
        ok, output = run_unittest(directory, HIDDEN_NAME)
        return not ok, output


# ---------------------------------------------------------------------------
# build


def enclosing_function(source: str, lineno: int) -> str:
    tree = ast.parse(source)
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= lineno <= node.end_lineno:
                if best is None or node.lineno > best.lineno:
                    best = node
    return best.name if best else "<module>"


@dataclass
class Candidate:
    task: str
    function: str
    target: object
    case: object
    public_output: str
    hidden_output: str
    mode: str = "visible"
    drift: str = "dedent_last"


def build_candidates(task: str, *, per_task: int, mode: str = "visible", max_attempts: int = 400) -> list[Candidate]:
    ref_path = REFERENCE / f"{task}.py"
    tests_path = TASKS / task / "tests_public.py"
    hidden_path = HIDDEN / f"{task}.py"
    if not (ref_path.exists() and tests_path.exists() and hidden_path.exists()):
        raise SystemExit(f"missing reference/tests/hidden for {task}")
    reference = ref_path.read_text(encoding="utf-8")
    tests = tests_path.read_text(encoding="utf-8")
    hidden = hidden_path.read_text(encoding="utf-8")
    if mode == "silent":
        targets = else_drift_targets(reference, task, per_file=200)
        drift = "hoist_else"
    else:
        targets = code_drift_targets(reference, task, per_file=200)
        drift = "dedent_last"
    # Prefer the public entry points; fall back to any function with a suitable
    # last statement.
    targets.sort(
        key=lambda t: (
            PREFERRED_FUNCTIONS.index(enclosing_function(reference, t.lineno))
            if enclosing_function(reference, t.lineno) in PREFERRED_FUNCTIONS
            else len(PREFERRED_FUNCTIONS),
            t.lineno,
        )
    )
    chosen: list[Candidate] = []
    seen_functions: Counter = Counter()
    attempts = 0
    for target in targets:
        if len(chosen) >= per_task or attempts >= max_attempts:
            break
        attempts += 1
        try:
            case = make_case(reference, target, drift)
        except InjectionError:
            continue
        if not compile_ok(case.source):
            continue
        result = check_source(case.source)
        if not result.errors:
            continue
        public_failed, public_output = public_fails(case.source, tests)
        hidden_failed, hidden_output = hidden_fails(case.source, tests, hidden)
        if mode == "silent":
            if public_failed or not hidden_failed:
                continue
        else:
            if not public_failed or not hidden_failed:
                continue
        function = enclosing_function(reference, target.lineno)
        if seen_functions[function] >= 2:
            continue
        seen_functions[function] += 1
        chosen.append(
            Candidate(
                task=task,
                function=function,
                target=target,
                case=case,
                public_output=public_output,
                hidden_output=hidden_output,
                mode=mode,
                drift=drift,
            )
        )
    return chosen


def task_slug(task: str, function: str, mode: str, drift: str, index: int) -> str:
    safe = function.replace("<", "").replace(">", "")
    mode_part = "" if mode == "visible" else f"{mode}__"
    return f"{task}__{safe}__{mode_part}{drift}__{index:02d}"


def build_task(task: str, candidate: Candidate, index: int, *, force: bool) -> Path:
    slug = task_slug(task, candidate.function, candidate.mode, candidate.drift, index)
    directory = TASK_DIR / slug
    if directory.exists():
        if not force:
            print(f"skip {slug} (exists)")
            return directory
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    reference = (REFERENCE / f"{task}.py").read_text(encoding="utf-8")
    tests = (TASKS / task / "tests_public.py").read_text(encoding="utf-8")
    hidden = (HIDDEN / f"{task}.py").read_text(encoding="utf-8")
    write_text(directory / "start.py", candidate.case.source)
    write_text(directory / "tests_public.py", tests)
    write_text(directory / "hidden.py", hidden)
    write_text(directory / "expected.py", reference)
    write_text(directory / "task.md", build_task_md(task, candidate, candidate.mode))
    meta = {
        "task": task,
        "slug": slug,
        "drift": candidate.drift,
        "mode": candidate.mode,
        "function": candidate.function,
        "target": {
            "kind": candidate.target.kind,
            "lineno": candidate.target.lineno,
            "end_lineno": candidate.target.end_lineno,
            "col": candidate.target.col,
            "span": candidate.target.span,
        },
        "anchor_line": candidate.case.anchor_line,
        "drift_line": candidate.case.drift_line,
        "expected_codes": list(candidate.case.expected_codes),
        "diff": candidate.case.meta.get("changed"),
        "tests_sha256": sha256_text(tests),
        "hidden_sha256": sha256_text(hidden),
        "start_sha256": sha256_text(candidate.case.source),
        "expected_sha256": sha256_text(reference),
        "public_failure": candidate.public_output[-1000:],
        "hidden_failure": candidate.hidden_output[-1000:],
    }
    write_json(directory / "meta.json", meta)
    return directory


def build_task_md(task: str, candidate: Candidate, mode: str) -> str:
    if mode == "silent":
        signal = (
            "The public tests **pass**, but the hidden tests fail.  The drift is "
            "in a branch the public examples do not exercise.  Use the anchors and "
            "`check` (in the check_on arm) to locate it; do not assume that a green "
            "public suite means the file is correct."
        )
    else:
        signal = (
            "The public tests **fail**; hidden tests are used for scoring but are "
            "not visible."
        )
    return f"""# Repair task: {task}

`solution.py` is a working solution to the original `{task}` refactor task.
A previous edit introduced a **structural drift**: the code still parses, but a
statement now belongs to a different block than intended. The `# end ...`
anchors in the file describe the intended block structure from before the edit.

{signal}

Your job is to restore the intended behaviour.

Rules:

- Edit `solution.py` in place.
- Do **not** modify `task.md` or `tests_public.py`.
- Do **not** modify, add, or remove any `# end ...` anchor. They are assertions,
  not decoration. If the anchors and the code disagree, fix the code.
- At most 3 repair attempts (a repair attempt is a test run that fails).
- The structural drift is local. Do not rewrite the whole function.
"""


def cmd_build(args: argparse.Namespace) -> int:
    tasks = args.tasks.split(",") if args.tasks else ["T1_pipeline"]
    total = 0
    for task in tasks:
        candidates = build_candidates(task, per_task=args.per_task, mode=args.mode)
        print(f"{task}: {len(candidates)} usable candidate(s)")
        for index, candidate in enumerate(candidates, 1):
            build_task(task, candidate, index, force=args.force)
            total += 1
    print(f"built {total} repair task(s) under {TASK_DIR}")
    return 0


# ---------------------------------------------------------------------------
# init


def arm_text(arm: str, run_rel: str) -> str:
    if arm == "check_on":
        return f"""# Arm: check_on

- Before editing, run:

  ```bash
  pyforai check {run_rel}/solution.py
  ```

  The diagnostic names the anchor line and the block it belongs to. Use it to
  locate the drift; do not guess.
- After each edit, run `check` again and fix every anchor error.
- Do not modify the anchors themselves; if `check` reports a mismatch, the code
  is what moved.
- You may also run the public tests; use `check` as the primary locator.
"""
    if arm == "check_off":
        return f"""# Arm: check_off

- Do **not** run `pyforai` (no `check`, `fmt`, `wrap`, `replace-body`, `move`).
- Debug from the public tests and the code. The anchors in the file are still
  there, but treat them as ordinary comments; do not use them as a locator.
- Do not modify the anchors themselves.
"""
    raise SystemExit(f"unknown arm: {arm}")


def build_prompt(task: str, arm: str, run_name: str, mode: str = "visible") -> str:
    run_rel = f"bench/e1/repair/runs/{run_name}"
    if mode == "silent":
        signal = "The public tests pass, but the hidden tests fail; the drift is in a branch the public examples do not exercise."
    else:
        signal = "The public tests fail."
    return f"""# Controlled repair experiment

Work from the project root: `{ROOT}`.
Your run directory: `{run_rel}`.

`solution.py` is a working solution to the original `{task}` task, but a
previous edit introduced a structural drift. {signal}

Read `{run_rel}/task.md` and `{run_rel}/tests_public.py` first.

## Goal

Make `{run_rel}/solution.py` pass the public tests:

```bash
(cd {run_rel} && python -m unittest tests_public -v)
```

The hidden tests are used for scoring and are not visible. Do not try to read
`bench/e1/repair/sources`, `bench/e1/repair/tasks`, or another run.

## Arm rules

{arm_text(arm, run_rel)}

## Logging (required)

- At the start: `date +%s > {run_rel}/started_at.txt`
- After each edit, snapshot the file:

  ```bash
  mkdir -p {run_rel}/edits
  cp {run_rel}/solution.py {run_rel}/edits/$(date +%s)_after.py
  echo '{{"ts": '$(date +%s)', "file": "solution.py"}}' >> {run_rel}/edits.jsonl
  ```

- After each test run, append one line to `{run_rel}/attempts.log`:
  `<epoch> attempt <n> <pass|fail>`
- Append every shell command that touches `pyforai` to `{run_rel}/commands.log`.
- If your runtime reports token usage, write it to `{run_rel}/usage.json` as
  `{{"input_tokens": <n>, "output_tokens": <n>}}`; otherwise leave it absent.
- At the end: `date +%s > {run_rel}/finished_at.txt`

## Rules

- Do not modify `task.md`, `tests_public.py`, or any `# end ...` anchor.
- At most 3 repair attempts.
- Do not read other runs, `bench/e1/repair/sources`, or
  `bench/e1/repair/tasks`.
- When done, write a 3-line summary to `{run_rel}/summary.md` and reply with the
  same summary.
"""


def cmd_init(args: argparse.Namespace) -> int:
    arms = args.arms.split(",") if args.arms else list(ARM_NAMES)
    tasks = args.tasks.split(",") if args.tasks else sorted(p.name for p in TASK_DIR.iterdir() if p.is_dir())
    if not tasks:
        raise SystemExit("no repair tasks; run `build` first")
    reps = max(1, args.reps)
    for task in tasks:
        task_dir = TASK_DIR / task
        if not task_dir.is_dir():
            raise SystemExit(f"missing task: {task_dir}")
        meta = read_json(task_dir / "meta.json")
        for arm in arms:
            if arm not in ARM_NAMES:
                raise SystemExit(f"unknown arm: {arm}")
            for rep in range(1, reps + 1):
                run_name = f"{task}__{arm}__r{rep}" if reps > 1 else f"{task}__{arm}"
                run_dir = RUNS / run_name
                if run_dir.exists():
                    if not args.force:
                        print(f"skip {run_name} (exists)")
                        continue
                    shutil.rmtree(run_dir)
                run_dir.mkdir(parents=True)
                (run_dir / "edits").mkdir()
                copy_task_file(task_dir / "task.md", run_dir / "task.md")
                copy_task_file(task_dir / "tests_public.py", run_dir / "tests_public.py")
                copy_task_file(task_dir / "start.py", run_dir / "start.py")
                copy_task_file(task_dir / "start.py", run_dir / "solution.py")
                arm_rules = arm_text(arm, f"bench/e1/repair/runs/{run_name}")
                write_text(run_dir / "arm.md", arm_rules)
                write_text(run_dir / "prompt.md", build_prompt(task, arm, run_name, meta.get("mode", "visible")))
                run_json = {
                    "task": task,
                    "arm": arm,
                    "rep": rep,
                    "drift": meta["drift"],
                    "mode": meta.get("mode", "visible"),
                    "function": meta["function"],
                    "tests_sha256": meta["tests_sha256"],
                    "start_sha256": meta["start_sha256"],
                    "reference_sha256": meta["expected_sha256"],
                    "anchor_line": meta["anchor_line"],
                    "drift_line": meta["drift_line"],
                }
                write_json(run_dir / "run.json", run_json)
                print(f"created {run_name}")
    return 0


# ---------------------------------------------------------------------------
# score


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
    payload = 0
    for old, new in zip(snapshots, snapshots[1:]):
        payload += edit_payload_bytes(old, new)
    return {
        "edits_count": max(0, len(snapshots) - 1),
        "edit_payload_bytes": payload,
        "snapshots": len(snapshots),
    }


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
        "mode": meta.get("mode", "visible"),
        "function": meta.get("function"),
        "solution_exists": solution_path.exists(),
        "syntax_ok": False,
        "public_pass": False,
        "hidden_pass": False,
        "solved": False,
        "behavior_only": False,
        "anchors_modified": False,
        "anchor_errors": None,
        "anchor_count": 0,
        "anchor_errors_start": None,
        "exact_ast_match": False,
        "tampered_tests": False,
        "check_calls": 0,
        "pyforai_calls": 0,
        "help_calls": 0,
        "test_runs": None,
        "repair_attempts": None,
        "wall_time_s": None,
        "edits_count": 0,
        "edit_payload_bytes": 0,
        "snapshots": 0,
        "usage": None,
        "laundered": False,
        "summary": "",
        "public_output": "",
        "hidden_output": "",
        "check_output": "",
    }
    if solution:
        try:
            ast.parse(solution)
            metrics["syntax_ok"] = True
        except SyntaxError:
            pass
        result = check_path_cli(solution_path)
        metrics["anchor_errors"] = len([d for d in result["diagnostics"] if d.get("code") != "E010"])
        metrics["anchor_count"] = len(anchor_fingerprint(solution))
        metrics["check_output"] = "\n".join(
            f"{d.get('code')} L{d.get('line')}:C{d.get('col')} {d.get('message')}" for d in result["diagnostics"]
        )[:2000]
        start_result = check_path_cli(run_dir / "start.py") if start else None
        metrics["anchor_errors_start"] = len([d for d in start_result["diagnostics"] if d.get("code") != "E010"]) if start_result else None
        metrics["anchors_modified"] = anchor_fingerprint(start) != anchor_fingerprint(solution)
        expected_path = TASK_DIR / task / "expected.py"
        if expected_path.exists():
            expected = expected_path.read_text(encoding="utf-8")
            try:
                metrics["exact_ast_match"] = ast_fingerprint(solution) == ast_fingerprint(expected)
            except SyntaxError:
                metrics["exact_ast_match"] = False

    public_ok, public_output = run_unittest(run_dir, "tests_public")
    metrics["public_pass"] = public_ok
    metrics["public_output"] = public_output
    hidden_source = TASK_DIR / task / "hidden.py"
    if hidden_source.exists():
        shutil.copy2(hidden_source, run_dir / HIDDEN_NAME)
        hidden_ok, hidden_output = run_unittest(run_dir, "test_hidden")
        metrics["hidden_pass"] = hidden_ok
        metrics["hidden_output"] = hidden_output

    tests_path = run_dir / "tests_public.py"
    metrics["tampered_tests"] = not (
        tests_path.exists() and sha256_file(tests_path) == meta.get("tests_sha256")
    )
    metrics["behavior_only"] = metrics["public_pass"] and metrics["hidden_pass"]
    metrics["solved"] = (
        metrics["behavior_only"]
        and not metrics["anchors_modified"]
        and metrics["anchor_errors"] == 0
    )
    metrics["laundered"] = metrics["anchors_modified"] and metrics["anchor_errors"] == 0
    metrics["test_runs"], metrics["repair_attempts"] = count_log_failures(run_dir / "attempts.log")
    metrics["check_calls"], metrics["pyforai_calls"], metrics["help_calls"] = count_check_calls(run_dir / "commands.log")
    started = parse_epoch(run_dir / "started_at.txt")
    finished = parse_epoch(run_dir / "finished_at.txt")
    if started is not None and finished is not None and finished >= started:
        metrics["wall_time_s"] = finished - started
    metrics.update(_edits_metrics(run_dir))
    usage = read_json(run_dir / "usage.json")
    if isinstance(usage, dict):
        metrics["usage"] = usage
    summary = run_dir / "summary.md"
    if summary.exists():
        metrics["summary"] = summary.read_text(encoding="utf-8", errors="replace")[:1000]
    write_json(run_dir / "metrics.json", metrics)
    return metrics


def cmd_score(args: argparse.Namespace) -> int:
    run_dirs = [Path(path) for path in args.runs] if args.runs else sorted(p.parent for p in RUNS.glob("*/run.json"))
    if not run_dirs:
        raise SystemExit("no runs; run `init` first")
    for run_dir in run_dirs:
        metrics = score_run(run_dir)
        print(
            f"{metrics['run']}: solved={metrics['solved']} public={metrics['public_pass']} "
            f"hidden={metrics['hidden_pass']} anchors_modified={metrics['anchors_modified']} "
            f"check_calls={metrics['check_calls']} edits={metrics['edits_count']}"
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


def _aggregate(metrics: list[dict]) -> list[dict]:
    rows = []
    for arm in ARM_NAMES:
        group = [m for m in metrics if m["arm"] == arm]
        if not group:
            continue
        rows.append(
            {
                "arm": arm,
                "n": len(group),
                "solved": sum(1 for m in group if m["solved"]),
                "behavior_only": sum(1 for m in group if m["behavior_only"]),
                "anchors_modified": sum(1 for m in group if m["anchors_modified"]),
                "laundered": sum(1 for m in group if m["laundered"]),
                "check_used": sum(1 for m in group if m["check_calls"] > 0),
                "mean_attempts": _mean([m["repair_attempts"] for m in group]),
                "mean_wall": _mean([m["wall_time_s"] for m in group]),
                "mean_payload": _mean([m["edit_payload_bytes"] for m in group]),
                "mean_edits": _mean([m["edits_count"] for m in group]),
            }
        )
    return rows


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def cmd_report(args: argparse.Namespace) -> int:
    files = sorted(RUNS.glob("*/metrics.json"))
    if files:
        metrics = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    else:
        # After a cleanup the raw run directories may be gone; the aggregate
        # metrics file is retained so the report can still be regenerated.
        archive = RESULTS / "metrics.jsonl"
        if not archive.exists():
            raise SystemExit("no metrics; run `score` first")
        metrics = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line.strip()]
    per_run_rows = []
    for m in sorted(metrics, key=lambda x: (x["task"], x["arm"])):
        per_run_rows.append(
            [
                m["task"],
                m.get("mode", "visible"),
                m["function"],
                m["arm"],
                "yes" if m["solved"] else "no",
                "yes" if m["public_pass"] else "no",
                "yes" if m["hidden_pass"] else "no",
                "YES" if m["anchors_modified"] else "no",
                _fmt(m["anchor_errors"]),
                str(m["check_calls"]),
                _fmt(m["repair_attempts"]),
                _fmt(m["wall_time_s"]),
                str(m["edit_payload_bytes"]),
            ]
        )
    aggregate_rows = []
    for row in _aggregate(metrics):
        aggregate_rows.append(
            [
                row["arm"],
                str(row["n"]),
                f"{row['solved']}/{row['n']}",
                f"{row['behavior_only']}/{row['n']}",
                str(row["anchors_modified"]),
                str(row["laundered"]),
                f"{row['check_used']}/{row['n']}",
                _fmt(row["mean_attempts"]),
                _fmt(row["mean_wall"]),
                _fmt(row["mean_payload"]),
                _fmt(row["mean_edits"]),
            ]
        )
    report = f"""# E1 repair report

Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}

> Small pilot: two drift modes (visible and silent), one reference family, and
> a small number of runs.  It validates the harness and gives a direction; it is
> not a powered comparison.

## Per run

{_markdown_table(
    ["task", "mode", "fn", "arm", "solved", "public", "hidden", "anchors moved", "anchor err", "check calls", "failed attempts", "wall s", "payload B"],
    per_run_rows,
)}

## Aggregate

{_markdown_table(
    ["arm", "n", "solved", "behavior only", "anchors moved", "laundered", "check used", "attempts", "wall s", "payload B", "edits"],
    aggregate_rows,
)}

``solved`` = public + hidden pass, no anchor edited, and final ``check`` clean.
``behavior only`` ignores the anchor constraint.
``anchors moved`` is a position-independent comparison of every ``# end`` line.
``laundered`` means anchors changed and the final ``check`` is clean: the agent
made the checker agree by editing the assertion, not the code.
``payload B`` is the sum of added/removed bytes across the per-edit snapshots;
it is a proxy for output tokens, not a token count.

## Caveats

- N is small; treat differences as hypotheses.
- ``check_off`` compliance is prompt-level, not sandbox-level: the arm is told
  not to use ``pyforai``, and the score records whether it did.
- Attempts, wall time and snapshots are self-reported by the agent.  The
  public/hidden results and the anchor fingerprint are computed by the harness.
- ``visible`` drifts make the public tests fail; ``silent`` drifts leave the
  public tests green and fail only the hidden tests.  The silent mode is the
  one that can distinguish "check locates the drift" from "the tests already
  localise it".
- Both modes use the same `process`/`audit` reference, and `audit` is a
  near-identical twin of `process`.  A control-arm agent can diff the two
  functions to find a drift in `process`; that is a free oracle and a
  confound.  The next iteration should use a single-function reference or
  make the twin legitimately different.
"""
    (RESULTS / "report.md").parent.mkdir(parents=True, exist_ok=True)
    write_text(RESULTS / "report.md", report)
    (RESULTS / "metrics.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in metrics) + "\n", encoding="utf-8"
    )
    print(report)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for path in sorted(RUNS.glob("*/run.json")):
        run_dir = path.parent
        status = "unscored"
        if (run_dir / "metrics.json").exists():
            m = read_json(run_dir / "metrics.json")
            status = f"solved={m['solved']} public={m['public_pass']} hidden={m['hidden_pass']}"
        print(f"{run_dir.name}: {status}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build repair tasks from reference solutions")
    build.add_argument("--tasks", help="comma-separated T-family task ids")
    build.add_argument("--per-task", type=int, default=1)
    build.add_argument("--mode", choices=("visible", "silent"), default="visible")
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=cmd_build)

    init = sub.add_parser("init", help="create run directories and prompts")
    init.add_argument("--tasks", help="comma-separated task slugs")
    init.add_argument("--arms", default=",".join(ARM_NAMES))
    init.add_argument("--reps", type=int, default=1)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    score = sub.add_parser("score", help="score run artifacts")
    score.add_argument("runs", nargs="*")
    score.set_defaults(func=cmd_score)

    report = sub.add_parser("report", help="aggregate metrics")
    report.set_defaults(func=cmd_report)

    list_parser = sub.add_parser("list", help="list runs")
    list_parser.set_defaults(func=cmd_list)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
