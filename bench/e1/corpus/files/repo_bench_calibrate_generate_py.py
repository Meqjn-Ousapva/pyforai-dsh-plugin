#!/usr/bin/env python3
"""Generate the calibration ladder for the three-arm experiment.

Each level uses the same refactor contract but a larger per-record branch
ladder.  The public tests cover the structural requirements; the hidden test
differential-compares the agent's `process` with a reference implementation
across every branch, so preserving behavior is what actually matters.

Usage:
    python3 bench/calibrate/generate.py
    python3 bench/calibrate/generate.py --levels 2,4,6,8,10,12,14,16
    python3 bench/calibrate/generate.py --validate
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BENCH = ROOT / "bench"

# kind -> branch body relative to the `if record.kind == "...":` line
BRANCH_BODIES: dict[str, list[str]] = {
    "alpha": [
        "if entry.amount > 100:",
        '    report["matched"] += 2',
        "else:",
        '    report["matched"] += 1',
    ],
    "beta": [
        'if entry.status == "ok":',
        '    report["matched"] += 1',
        "else:",
        '    report["errors"].append((record.id, entry.id, "status"))',
    ],
    "gamma": [
        "if entry.amount % 2 == 0:",
        '    report["matched"] += 1',
        "else:",
        '    report["errors"].append((record.id, entry.id, "parity"))',
    ],
    "delta": [
        "if entry.amount >= 50:",
        '    report["matched"] += 3',
        "else:",
        '    report["matched"] += 1',
    ],
    "epsilon": [
        'if entry.status in ("ok", "new"):',
        '    report["matched"] += 1',
        "else:",
        '    report["errors"].append((record.id, entry.id, "status"))',
    ],
    "zeta": [
        "if entry.amount > 1000:",
        '    report["errors"].append((record.id, entry.id, "limit"))',
        "else:",
        '    report["matched"] += 1',
    ],
    "eta": [
        'if entry.status == "ok":',
        "    if entry.amount > 10:",
        '        report["matched"] += 2',
        "    else:",
        '        report["matched"] += 1',
        "else:",
        '    report["errors"].append((record.id, entry.id, "status"))',
    ],
    "theta": [
        'report["matched"] += 4',
    ],
    "iota": [
        'if entry.status == "hold":',
        '    report["errors"].append((record.id, entry.id, "hold"))',
        "else:",
        '    report["matched"] += 1',
    ],
    "kappa": [
        "if entry.amount > 500:",
        '    report["matched"] += 2',
        "else:",
        '    report["matched"] += 1',
    ],
    "mu": [
        'if entry.status == "new":',
        '    report["matched"] += 1',
        "else:",
        '    report["errors"].append((record.id, entry.id, "status"))',
    ],
    "nu": [
        "if entry.amount > 200:",
        '    report["matched"] += 2',
        "elif entry.amount > 50:",
        '    report["matched"] += 1',
        "else:",
        '    report["errors"].append((record.id, entry.id, "small"))',
    ],
    "xi": [
        'if entry.status == "ok" and entry.amount > 100:',
        '    report["matched"] += 2',
        "else:",
        '    report["matched"] += 1',
    ],
    "omicron": [
        'report["matched"] += 1',
    ],
    "pi": [
        "if entry.amount % 3 == 0:",
        '    report["matched"] += 2',
        "else:",
        '    report["errors"].append((record.id, entry.id, "mod3"))',
    ],
    "rho": [
        'if entry.status == "ok":',
        "    if entry.amount > 1000:",
        '        report["errors"].append((record.id, entry.id, "limit"))',
        "    else:",
        '        report["matched"] += 1',
        "else:",
        '    report["errors"].append((record.id, entry.id, "status"))',
    ],
}
for _index in range(17, 33):
    _name = f"kind_{_index}"
    BRANCH_BODIES[_name] = [
        f"if entry.amount % {_index} == 0:",
        '    report["matched"] += 1',
        "else:",
        f'    report["errors"].append((record.id, entry.id, "mod{_index}"))',
    ]

KIND_ORDER = list(BRANCH_BODIES)

CONSTRAINT = """
5. Do not add new top-level functions, methods, classes, or lambdas. Keep the
   refactor inside `process`; use the existing classes. `tests_public.py`
   includes a structural check for this.
"""

STRUCTURE_TEST = '''
    def test_structure(self):
        import ast
        import inspect
        import solution

        tree = ast.parse(inspect.getsource(solution))
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.FunctionDef)],
            ["process"],
        )
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.ClassDef)],
            ["Record", "Entry", "Backend"],
        )
        allowed = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "process":
                allowed.add(id(node))
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name in ("__init__", "get"):
                        allowed.add(id(child))
        extra = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and id(node) not in allowed
        ]
        self.assertEqual(extra, [])
        self.assertEqual([node for node in ast.walk(tree) if isinstance(node, ast.Lambda)], [])
'''

START_TEMPLATE = '''"""Pipeline calibration task __TASK__ (__N__ record kinds)."""

from __future__ import annotations


class Record:
    def __init__(self, id, kind, currency="USD", active=True):
        self.id = id
        self.kind = kind
        self.currency = currency
        self.active = active


class Entry:
    def __init__(self, id, amount, currency="USD", status="ok"):
        self.id = id
        self.amount = amount
        self.currency = currency
        self.status = status


class Backend:
    def __init__(self, entries):
        self.entries = entries

    def get(self, record_id):
        if record_id == "boom":
            raise ConnectionError("backend unavailable")
        return self.entries.get(record_id, [])


def process(records, backend, notifier=None):
    report = {"matched": 0, "missing": [], "errors": [], "notified": 0}
    for record in records:
        if not record.active:
            report["missing"].append(record.id)
        else:
            for entry in backend.get(record.id):
                if entry.status == "skip":
                    continue
                if entry.amount <= 0:
                    report["errors"].append((record.id, entry.id, "amount"))
                elif entry.currency != record.currency:
                    report["errors"].append((record.id, entry.id, "currency"))
                else:
__BRANCHES__
            if notifier is not None:
                notifier(record.id, report)
                report["notified"] += 1
    return report
'''

REFERENCE_TEMPLATE = '''def reference_process(records, backend, notifier=None):
    report = {"matched": 0, "missing": [], "errors": [], "notified": 0}
    if not records:
        if notifier is not None:
            notifier(report)
            report["notified"] += 1
        return report
    for record in records:
        if not record.active:
            report["missing"].append(record.id)
            continue
        try:
            for entry in backend.get(record.id):
                if entry.status == "skip":
                    continue
                if entry.amount <= 0:
                    report["errors"].append((record.id, entry.id, "amount"))
                elif entry.currency != record.currency:
                    report["errors"].append((record.id, entry.id, "currency"))
                else:
__BRANCHES__
        except Exception as exc:
            report["errors"].append((record.id, "record", str(exc)))
    if notifier is not None:
        notifier(report)
        report["notified"] += 1
    return report
'''

TASK_TEMPLATE = '''# Task __TASK__: pipeline error isolation (__N__ kinds)

`solution.py` contains a working `process(records, backend, notifier=None)`.
Refactor it:

1. If `records` is empty, call `notifier(report)` once if provided, increment
   `report["notified"]`, and return `report`.
2. Wrap the per-record processing in `try/except Exception as exc`. On failure,
   append `(record.id, "record", str(exc))` to `report["errors"]` and continue
   with the next record.
3. Call `notifier(report)` exactly once at the end, not once per record, and
   increment `report["notified"]` by 1. If no notifier is provided, leave it 0.
4. Preserve all existing branch behavior and the `Record`, `Entry`, `Backend`
   classes and the `process` signature.
__CONSTRAINT__
The public tests are in `tests_public.py`. Edit `solution.py` in place.
'''

PUBLIC_TEMPLATE = '''"""Public tests for __TASK__."""

from __future__ import annotations

import unittest

from solution import Backend, Entry, Record, process


class PipelinePublicTests(unittest.TestCase):
    def test_empty_calls_notifier_once(self):
        calls = []
        report = process([], Backend({}), calls.append)
        self.assertEqual(report["matched"], 0)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["notified"], 1)
        self.assertEqual(len(calls), 1)

    def test_boom_does_not_abort(self):
        records = [Record("a", "alpha"), Record("boom", "alpha"), Record("b", "beta")]
        backend = Backend({"a": [Entry(1, 150)], "b": [Entry(2, 10)]})
        report = process(records, backend, lambda report: None)
        self.assertIn(("boom", "record", "backend unavailable"), report["errors"])
        self.assertGreaterEqual(report["matched"], 1)
        self.assertEqual(report["notified"], 1)

    def test_inactive_and_error_categories(self):
        records = [Record("x", "alpha", active=False), Record("a", "alpha")]
        backend = Backend({"a": [Entry(1, -5), Entry(2, 10, currency="EUR")]})
        report = process(records, backend, None)
        self.assertEqual(report["missing"], ["x"])
        self.assertIn(("a", 1, "amount"), report["errors"])
        self.assertIn(("a", 2, "currency"), report["errors"])
        self.assertEqual(report["notified"], 0)
__STRUCTURE__'''

HIDDEN_TEMPLATE = '''"""Hidden differential tests for __TASK__."""

from __future__ import annotations

import copy
import unittest

from solution import Backend, Entry, Record, process


__REFERENCE__


KINDS = __KINDS__


def entries():
    return [
        Entry(1, 150),
        Entry(2, 50),
        Entry(3, -1),
        Entry(4, 10, currency="EUR"),
        Entry(5, 50, status="skip"),
        Entry(6, 50, status="hold"),
        Entry(7, 2000),
        Entry(8, 10, status="new"),
        Entry(9, 10, status="ok"),
    ]


class PipelineHiddenTests(unittest.TestCase):
    def _check(self, records, data, use_notifier=True):
        expected_calls = []
        actual_calls = []

        def expected_notifier(report):
            expected_calls.append(copy.deepcopy(report))

        def actual_notifier(report):
            actual_calls.append(copy.deepcopy(report))

        expected = reference_process(
            records,
            Backend(data),
            expected_notifier if use_notifier else None,
        )
        actual = process(
            records,
            Backend(data),
            actual_notifier if use_notifier else None,
        )
        self.assertEqual(actual, expected)
        self.assertEqual(actual_calls, expected_calls)

    def test_empty(self):
        self._check([], {}, True)
        self._check([], {}, False)

    def test_each_kind(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self._check([Record(kind, kind)], {kind: entries()}, True)
                self._check([Record(kind, kind)], {kind: entries()}, False)

    def test_mixed(self):
        records = [Record(kind, kind) for kind in KINDS]
        records += [
            Record("inactive", "alpha", active=False),
            Record("unknown", "unknown"),
        ]
        data = {kind: entries() for kind in KINDS}
        self._check(records, data, True)
        self._check(records, data, False)

    def test_boom_positions(self):
        base = [Record("a", "alpha"), Record("b", "beta")]
        data = {"a": entries(), "b": entries()}
        for index in range(len(base) + 1):
            records = base[:index] + [Record("boom", "alpha")] + base[index:]
            with self.subTest(index=index):
                self._check(records, data, True)
__STRUCTURE__'''


def branch_block(kinds: list[str], indent: int = 20) -> str:
    lines: list[str] = []
    for index, kind in enumerate(kinds):
        keyword = "if" if index == 0 else "elif"
        lines.append(f'{keyword} record.kind == "{kind}":')
        body = textwrap.indent("\n".join(BRANCH_BODIES[kind]), "    ")
        lines.extend(body.splitlines())
    lines.append("else:")
    lines.append('    report["errors"].append((record.id, entry.id, "kind"))')
    return textwrap.indent("\n".join(lines), " " * indent)


def build_start(task: str, kinds: list[str]) -> str:
    return (
        START_TEMPLATE.replace("__TASK__", task)
        .replace("__N__", str(len(kinds)))
        .replace("__BRANCHES__", branch_block(kinds))
    )


def build_reference(kinds: list[str]) -> str:
    return REFERENCE_TEMPLATE.replace("__BRANCHES__", branch_block(kinds))


def build_reference_solution(kinds: list[str]) -> str:
    start = build_start("reference", kinds)
    classes = start.split("def process(", 1)[0]
    reference = build_reference(kinds).replace("def reference_process(", "def process(", 1)
    return classes + reference


def build_task(task: str, kinds: list[str], structural: bool) -> str:
    return (
        TASK_TEMPLATE.replace("__TASK__", task)
        .replace("__N__", str(len(kinds)))
        .replace("__CONSTRAINT__", CONSTRAINT if structural else "")
    )


def build_public(task: str, structural: bool) -> str:
    return (
        PUBLIC_TEMPLATE.replace("__TASK__", task)
        .replace("__STRUCTURE__", STRUCTURE_TEST if structural else "")
    )


def build_hidden(task: str, kinds: list[str], structural: bool) -> str:
    return (
        HIDDEN_TEMPLATE.replace("__TASK__", task)
        .replace("__REFERENCE__", build_reference(kinds).rstrip())
        .replace("__KINDS__", repr(kinds))
        .replace("__STRUCTURE__", STRUCTURE_TEST if structural else "")
    )


def write_task(
    task: str, kinds: list[str], structural: bool, reference_dir: Path | None
) -> None:
    task_dir = BENCH / "tasks" / task
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.md").write_text(build_task(task, kinds, structural), encoding="utf-8")
    (task_dir / "start.py").write_text(build_start(task, kinds), encoding="utf-8")
    (task_dir / "tests_public.py").write_text(build_public(task, structural), encoding="utf-8")
    (BENCH / "hidden").mkdir(parents=True, exist_ok=True)
    (BENCH / "hidden" / f"{task}.py").write_text(
        build_hidden(task, kinds, structural), encoding="utf-8"
    )
    if reference_dir is not None:
        reference_dir.mkdir(parents=True, exist_ok=True)
        (reference_dir / f"{task}.py").write_text(
            build_reference_solution(kinds), encoding="utf-8"
        )


def validate(tasks: list[tuple[str, list[str]]], reference_dir: Path) -> bool:
    ok = True
    for task, kinds in tasks:
        with tempfile.TemporaryDirectory(prefix="pyforai-calibrate-") as temp:
            run_dir = Path(temp)
            shutil.copy2(reference_dir / f"{task}.py", run_dir / "solution.py")
            shutil.copy2(BENCH / "tasks" / task / "tests_public.py", run_dir / "tests_public.py")
            shutil.copy2(BENCH / "hidden" / f"{task}.py", run_dir / "test_hidden.py")
            for module in ("tests_public", "test_hidden"):
                proc = subprocess.run(
                    [sys.executable, "-m", "unittest", module, "-v"],
                    cwd=run_dir,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    ok = False
                    print(f"FAIL {task} {module}")
                    print((proc.stdout + proc.stderr)[-2000:])
                else:
                    print(f"ok {task} {module}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--levels",
        default="2,4,6,8,10,12,14,16",
        help="comma-separated branch counts",
    )
    parser.add_argument(
        "--family",
        choices=("C", "S"),
        default="C",
        help="C = helper-allowed ceiling ladder; S = structural in-place ladder",
    )
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    counts = [int(part) for part in args.levels.split(",") if part.strip()]
    if any(count < 2 or count > len(KIND_ORDER) for count in counts):
        raise SystemExit(f"levels must be between 2 and {len(KIND_ORDER)}")

    reference_dir = BENCH / "calibrate" / "_reference"
    structural = args.family == "S"
    tasks: list[tuple[str, list[str]]] = []
    for index, count in enumerate(counts, start=1):
        task = f"{args.family}{index}_pipeline"
        kinds = KIND_ORDER[:count]
        write_task(task, kinds, structural, reference_dir)
        tasks.append((task, kinds))
        print(f"generated {task}: {count} kinds, {len(kinds) * 7 + 30}ish lines")

    if args.validate:
        if not validate(tasks, reference_dir):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
