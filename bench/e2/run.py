"""E2: forced-reindent structural editing.

Question: when a correct edit requires re-indenting a large block, does a
structural tool (`pyforai wrap`) reduce the amount of text the model must emit
and the collateral changes, compared with hand editing and a formatter-only
workflow?

Tasks are generated with block sizes 20/80/200 statements.  The only correct
edit is to wrap the body of the `for` loop in `try/except`; there is no
`else:`-reuse shortcut.  The reference and the start differ only by the
`try`/`except` and the indentation of the body.

Arms:
    manual     -- edit directly; no pyforai, no formatter
    formatter  -- edit directly, then run black; no pyforai
    plugin     -- use pyforai wrap, then check

Metrics:
    solved          public + hidden pass and the target AST matches
    target_ast      solution AST equals the expected AST
    collateral      AST outside the target `for` body changed
    required_reindent  body statements that must move one level
    snapshot_payload  bytes in the agent's per-edit snapshots
    tool_command_bytes  bytes in pyforai command lines
    first_edit_s, wall_s, check_calls, tool_calls

Usage::

    python -m bench.e2.run build --sizes 20,80,200
    python -m bench.e2.run init --arms manual,formatter,plugin
    python -m bench.e2.run score
    python -m bench.e2.run report
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
from pathlib import Path
from typing import Optional

from ..e1.common import (
    E1,
    anchor_fingerprint,
    check_path_cli,
    count_check_calls,
    count_log_failures,
    edit_payload_bytes,
    parse_epoch,
    read_json,
    sha256_text,
    write_json,
    write_text,
)
from ..e1.repair import run_unittest

E2 = Path(__file__).resolve().parent
TASKS = E2 / "tasks"
RUNS = E2 / "runs"
RESULTS = E2 / "results"
ARMS = ("manual", "formatter", "plugin")
HIDDEN_NAME = "test_hidden.py"


# ---------------------------------------------------------------------------
# task generation


def make_source(size: int) -> tuple[str, str, int]:
    body = [
        'if record.kind == "skip":',
        "    continue",
        "if record.fail:",
        '    raise ValueError("boom")',
        'report["ok"] += 1',
        'report["trace"].append(record.id)',
    ]
    for index in range(size):
        body.append(f'report["trace"].append({index})')
    prefix = '''from __future__ import annotations


class Record:
    def __init__(self, id, kind="ok", fail=False):
        self.id = id
        self.kind = kind
        self.fail = fail


def process(records):
    report = {"ok": 0, "errors": [], "trace": []}
'''
    start_body = "".join(f"        {line}\n" for line in body)
    expected_body = "".join(f"            {line}\n" for line in body)
    start = prefix + "    for record in records:\n" + start_body + "    return report\n"
    # pyforai's ``wrap --header`` wraps a whole block, so the task wraps the
    # ``for`` statement itself.  The loop header and body are both re-indented.
    expected = (
        prefix
        + "    try:\n"
        + "        for record in records:\n"
        + expected_body
        + "    except Exception as exc:\n"
        + '        report["errors"].append((record.id, str(exc)))\n'
        + "    return report\n"
    )
    loop_line = prefix.count("\n") + 1
    return start, expected, loop_line


def tests_source() -> tuple[str, str]:
    public = '''"""Public tests for E2 forced-reindent wrap."""

from __future__ import annotations

import unittest

from solution import Record, process


class PublicTests(unittest.TestCase):
    def test_normal(self):
        records = [Record("a"), Record("b")]
        report = process(records)
        self.assertEqual(report["ok"], 2)
        self.assertEqual(report["errors"], [])
        self.assertIn("a", report["trace"])

    def test_failure_stops_loop(self):
        records = [Record("a"), Record("bad", fail=True), Record("c")]
        report = process(records)
        self.assertEqual(report["ok"], 1)
        self.assertEqual(report["errors"], [("bad", "boom")])
        self.assertNotIn("c", report["trace"])

    def test_skip(self):
        records = [Record("a"), Record("s", kind="skip"), Record("b")]
        report = process(records)
        self.assertEqual(report["ok"], 2)
        self.assertNotIn("s", report["trace"])
'''
    hidden = '''"""Hidden tests for E2 forced-reindent wrap."""

from __future__ import annotations

import unittest

from solution import Record, process


class HiddenTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(process([]), {"ok": 0, "errors": [], "trace": []})

    def test_multiple_failures(self):
        records = [
            Record("a"),
            Record("bad1", fail=True),
            Record("bad2", fail=True),
            Record("b"),
        ]
        report = process(records)
        self.assertEqual(report["ok"], 1)
        self.assertEqual(report["errors"], [("bad1", "boom")])
        self.assertNotIn("b", report["trace"])

    def test_failure_at_end(self):
        records = [Record("a"), Record("bad", fail=True)]
        report = process(records)
        self.assertEqual(report["ok"], 1)
        self.assertEqual(report["errors"], [("bad", "boom")])

    def test_trace_order(self):
        records = [Record("x"), Record("y")]
        trace = process(records)["trace"]
        self.assertIn("x", trace)
        self.assertIn("y", trace)
        self.assertLess(trace.index("x"), trace.index("y"))
'''
    return public, hidden


def task_slug(size: int) -> str:
    return f"E2_wrap_{size:03d}"


def cmd_build(args: argparse.Namespace) -> int:
    sizes = [int(value) for value in args.sizes.split(",")]
    tests_public, hidden = tests_source()
    TASKS.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        start, expected, loop_line = make_source(size)
        slug = task_slug(size)
        directory = TASKS / slug
        if directory.exists() and not args.force:
            print(f"skip {slug} (exists)")
            continue
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        write_text(directory / "start.py", start)
        write_text(directory / "expected.py", expected)
        write_text(directory / "tests_public.py", tests_public)
        write_text(directory / "hidden.py", hidden)
        write_text(
            directory / "task.md",
            f"""# E2 task: wrap a {size}-statement loop

`solution.py` contains a working `process(records)` function with a
`for record in records:` loop (header at line {loop_line}).

Wrap the **entire `for` loop** in:

```python
try:
    for record in records:
        ...
except Exception as exc:
    report["errors"].append((record.id, str(exc)))
```

Behaviour:

- a failing record raises; append `(record.id, str(exc))` to
  `report["errors"]` and stop processing further records;
- successful and skipped records before the failure keep their behaviour;
- do not add new top-level functions, classes, or methods;
- keep `Record` and the `process` signature.

The public tests are in `tests_public.py`.  Edit `solution.py` in place.
""",
        )
        write_json(
            directory / "meta.json",
            {
                "slug": slug,
                "size": size,
                "required_reindent": size + 7,
                "loop_line": loop_line,
                "tests_sha256": sha256_text(tests_public),
                "start_sha256": sha256_text(start),
                "expected_sha256": sha256_text(expected),
            },
        )
        print(f"built {slug} (loop line {loop_line}, body {size + 6} lines)")
    return 0


# ---------------------------------------------------------------------------
# AST checks


def _process(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "process":
            return node
    raise ValueError("no process function")


def _target_for(tree: ast.Module) -> ast.For:
    for node in _process(tree).body:
        if isinstance(node, ast.For):
            return node
    for node in ast.walk(_process(tree)):
        if isinstance(node, ast.For):
            return node
    raise ValueError("no for loop")


def _normalize_outside(text: str) -> str:
    tree = ast.parse(text)
    target = _target_for(tree)
    target.body = [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def target_achieved(solution: str, expected: str) -> bool:
    try:
        return ast.dump(ast.parse(solution), include_attributes=False) == ast.dump(
            ast.parse(expected), include_attributes=False
        )
    except SyntaxError:
        return False


def collateral(solution: str, expected: str) -> bool:
    try:
        return _normalize_outside(solution) != _normalize_outside(expected)
    except (SyntaxError, ValueError):
        return True


# ---------------------------------------------------------------------------
# init


def arm_text(arm: str, run_rel: str, loop_line: int) -> str:
    if arm == "manual":
        return f"""# Arm: manual

- Edit `{run_rel}/solution.py` directly.
- Do **not** run `pyforai` or any structural editor.
- Do **not** write a script whose purpose is to re-indent or transform the file
  (no `sed`, `awk`, `python -c`, custom reindent scripts).  Use direct edits.
- You may run the public tests.
"""
    if arm == "formatter":
        return f"""# Arm: formatter

- Edit `{run_rel}/solution.py` directly.
- Do **not** run `pyforai` or any structural editor.
- Do **not** write a script whose purpose is to re-indent or transform the file.
- After editing, you may run `black {run_rel}/solution.py` if a formatter is
  installed.  The formatter arm is optional and was not part of the pilot.
- You may run the public tests.
"""
    if arm == "plugin":
        return f"""# Arm: plugin

- Use the structural tool instead of re-indenting by hand.  The loop header is
  at line {loop_line} of the start file; re-check it with `grep -n "for record"`
  if the file changed.

  ```bash
  pyforai wrap {run_rel}/solution.py --header <line> --kind try \\
    --except "Exception as exc" \\
    --handler 'report["errors"].append((record.id, str(exc)))'
  pyforai check {run_rel}/solution.py
  ```

- Do **not** hand-reindent the body.  If the tool fails, report the failure and
  fall back to a direct edit.
- You may run the public tests.
"""
    raise SystemExit(f"unknown arm: {arm}")


def build_prompt(task: str, arm: str, run_name: str, loop_line: int) -> str:
    run_rel = f"bench/e2/runs/{run_name}"
    return f"""# Controlled structural-editing experiment (E2)

Work from the project root: `{os.getcwd()}`.
Your run directory: `{run_rel}`.

Read `{run_rel}/task.md` and `{run_rel}/tests_public.py` first.

## Goal

Make `{run_rel}/solution.py` pass the public tests and the hidden tests.  The
hidden tests are not visible.  Do not read `bench/e2/tasks`, another run, or
`expected.py`.

## Arm rules

{arm_text(arm, run_rel, loop_line)}

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
- Append every command that touches `pyforai`/`black` to
  `{run_rel}/commands.log`.
- If your runtime reports token usage, write `{run_rel}/usage.json` as
  `{{"input_tokens": <n>, "output_tokens": <n>}}`.
- At the end: `date +%s > {run_rel}/finished_at.txt`

## Rules

- Do not modify `task.md` or `tests_public.py`.
- At most 3 repair attempts.
- When done, write a 3-line summary to `{run_rel}/summary.md` and reply with the
  same summary.
"""


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
                write_text(run_dir / "arm.md", arm_text(arm, f"bench/e2/runs/{run_name}", meta["loop_line"]))
                write_text(run_dir / "prompt.md", build_prompt(task, arm, run_name, meta["loop_line"]))
                write_json(
                    run_dir / "run.json",
                    {
                        "task": task,
                        "arm": arm,
                        "rep": rep,
                        "size": meta["size"],
                        "required_reindent": meta["required_reindent"],
                        "tests_sha256": meta["tests_sha256"],
                        "start_sha256": meta["start_sha256"],
                        "loop_line": meta["loop_line"],
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


def _snapshot_payload(run_dir: Path) -> int:
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
    return sum(edit_payload_bytes(old, new) for old, new in zip(snapshots, snapshots[1:]))


def _tool_command_bytes(run_dir: Path) -> int:
    path = run_dir / "commands.log"
    if not path.exists():
        return 0
    total = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "pyforai" in line or "black" in line:
            total += len(line) + 1
    return total


def score_run(run_dir: Path) -> dict:
    meta = read_json(run_dir / "run.json")
    task = meta["task"]
    arm = meta["arm"]
    solution_path = run_dir / "solution.py"
    solution = solution_path.read_text(encoding="utf-8", errors="replace") if solution_path.exists() else ""
    expected = (TASKS / task / "expected.py").read_text(encoding="utf-8")
    metrics = {
        "run": run_dir.name,
        "task": task,
        "arm": arm,
        "size": meta["size"],
        "required_reindent": meta["required_reindent"],
        "syntax_ok": False,
        "public_pass": False,
        "hidden_pass": False,
        "target_ast": False,
        "collateral": True,
        "solved": False,
        "first_try": False,
        "check_calls": 0,
        "pyforai_calls": 0,
        "test_runs": None,
        "failures": None,
        "first_edit_s": None,
        "wall_time_s": None,
        "snapshot_payload": 0,
        "tool_command_bytes": 0,
        "model_payload_proxy": 0,
        "usage": None,
        "summary": "",
    }
    if solution:
        try:
            ast.parse(solution)
            metrics["syntax_ok"] = True
        except SyntaxError:
            pass
        metrics["target_ast"] = target_achieved(solution, expected)
        metrics["collateral"] = collateral(solution, expected)
        metrics["check_calls"], metrics["pyforai_calls"], _ = count_check_calls(run_dir / "commands.log")
        result = check_path_cli(solution_path)
        metrics["anchor_errors"] = len([d for d in result["diagnostics"] if d.get("code") != "E010"])
    public_ok, _ = run_unittest(run_dir, "tests_public")
    metrics["public_pass"] = public_ok
    hidden_source = TASKS / task / "hidden.py"
    if hidden_source.exists():
        shutil.copy2(hidden_source, run_dir / HIDDEN_NAME)
        hidden_ok, _ = run_unittest(run_dir, "test_hidden")
        metrics["hidden_pass"] = hidden_ok
    metrics["test_runs"], metrics["failures"] = count_log_failures(run_dir / "attempts.log")
    metrics["first_edit_s"] = _first_edit_seconds(run_dir)
    started = parse_epoch(run_dir / "started_at.txt")
    finished = parse_epoch(run_dir / "finished_at.txt")
    if started is not None and finished is not None and finished >= started:
        metrics["wall_time_s"] = finished - started
    metrics["snapshot_payload"] = _snapshot_payload(run_dir)
    metrics["tool_command_bytes"] = _tool_command_bytes(run_dir)
    # For a tool arm the snapshot contains the tool's file changes, not the
    # model's output.  The command line is a better proxy for what the model
    # emitted; for manual arms the snapshot is the model's edit.
    metrics["model_payload_proxy"] = (
        metrics["tool_command_bytes"] if metrics["pyforai_calls"] > 0 else metrics["snapshot_payload"]
    )
    usage = read_json(run_dir / "usage.json")
    if isinstance(usage, dict):
        metrics["usage"] = usage
    metrics["solved"] = bool(
        metrics["syntax_ok"]
        and metrics["public_pass"]
        and metrics["hidden_pass"]
        and metrics["target_ast"]
        and not metrics["collateral"]
    )
    metrics["first_try"] = bool(metrics["solved"] and (metrics["failures"] or 0) == 0)
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
            f"target={m['target_ast']} collateral={m['collateral']} "
            f"payload={m['snapshot_payload']} tool={m['tool_command_bytes']} wall={m['wall_time_s']}s"
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
    headers = ["task", "size", "arm", "solved", "target", "collateral", "snapshot B", "model proxy B", "tool cmd B", "first edit s", "wall s", "check calls"]
    rows = []
    for m in sorted(metrics, key=lambda x: (x["size"], x["arm"])):
        rows.append(
            [
                m["task"],
                str(m["size"]),
                m["arm"],
                "yes" if m["solved"] else "no",
                "yes" if m["target_ast"] else "no",
                "YES" if m["collateral"] else "no",
                str(m["snapshot_payload"]),
                str(m["model_payload_proxy"]),
                str(m["tool_command_bytes"]),
                _fmt(m["first_edit_s"]),
                _fmt(m["wall_time_s"]),
                str(m["check_calls"]),
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
                f"{sum(1 for m in group if m['target_ast'])}/{len(group)}",
                _fmt(_mean([m["snapshot_payload"] for m in group])),
                _fmt(_mean([m["model_payload_proxy"] for m in group])),
                _fmt(_mean([m["tool_command_bytes"] for m in group])),
                _fmt(_mean([m["first_edit_s"] for m in group])),
                _fmt(_mean([m["wall_time_s"] for m in group])),
            ]
        )
    table = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
    table += "\n".join("| " + " | ".join(row) + " |" for row in rows)
    agg_headers = ["arm", "n", "solved", "target ast", "mean snapshot B", "mean model proxy B", "mean tool cmd B", "mean first edit s", "mean wall s"]
    agg = "| " + " | ".join(agg_headers) + " |\n|" + "|".join("---" for _ in agg_headers) + "|\n"
    agg += "\n".join("| " + " | ".join(row) + " |" for row in aggregates)
    report = f"""# E2 forced-reindent report

Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}

> Small pilot.  The task is to wrap a 20/80/200-statement loop body in
> `try/except`.  N is small; treat differences as hypotheses.

## Per run

{table}

## Aggregate

{agg}

``target`` = the solution AST equals the expected AST.
``collateral`` = AST outside the target `for` body changed.
``snapshot B`` = bytes in the agent's per-edit snapshots.  For a tool arm this
includes the tool's file changes, so it is *not* model output.
``model proxy B`` = snapshot bytes for manual arms, command bytes for tool
arms.  It is the best available proxy for emitted output; true token counts
are unavailable from the runner.  ``tool cmd B`` is the byte length of
pyforai/black command lines.
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
    build = sub.add_parser("build", help="generate forced-reindent tasks")
    build.add_argument("--sizes", default="20,80,200")
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=cmd_build)
    init = sub.add_parser("init", help="create runs")
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
