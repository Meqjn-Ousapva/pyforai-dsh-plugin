#!/usr/bin/env python3
"""Generate the two-function structural ladder T1..T6.

The S ladder reached 32 branches with a 100% arm-A hidden pass.  T adds a
second large function (`audit`) in the same file: `process` and `audit` each
carry the branch chain and each needs its own in-place `try/except` wrap.  The
no-helper structural check still applies, so the agent has to reindent two
large regions instead of extracting a shared helper.

Usage:
    python3 bench/calibrate/generate_t.py
    python3 bench/calibrate/generate_t.py --levels 4,8,12,16,20,24 --validate
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from generate import (  # noqa: E402
    KIND_ORDER,
    branch_block,
    build_reference,
    build_reference_solution,
    build_start,
)

BENCH = HERE.parent

AUDIT_START = '''def audit(records, backend):
    report = {"matched": 0, "errors": []}
    for record in records:
        if not record.active:
            continue
        for entry in backend.get(record.id):
            if entry.status == "skip":
                continue
            if entry.amount <= 0:
                report["errors"].append((record.id, entry.id, "amount"))
            elif entry.currency != record.currency:
                report["errors"].append((record.id, entry.id, "currency"))
            else:
__AUDIT_BRANCHES__
    return report
'''

AUDIT_REFERENCE = '''def reference_audit(records, backend):
    report = {"matched": 0, "errors": []}
    for record in records:
        if not record.active:
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
__AUDIT_BRANCHES__
        except Exception as exc:
            report["errors"].append((record.id, "audit", str(exc)))
    return report
'''

TASK_TEMPLATE = '''# Task __TASK__: two-function structural refactor (__N__ kinds)

`solution.py` contains a working `process(records, backend, notifier=None)` and
`audit(records, backend)`. Refactor both in place:

1. In `process`, if `records` is empty, call `notifier(report)` once if
   provided, increment `report["notified"]`, and return `report`.
2. In `process`, wrap the per-record processing in `try/except Exception as
   exc`. On failure append `(record.id, "record", str(exc))` to
   `report["errors"]` and continue with the next record.
3. In `process`, call `notifier(report)` exactly once at the end, not once per
   record, and increment `report["notified"]` by 1. If no notifier is provided,
   leave it 0.
4. In `audit`, wrap the per-record processing in `try/except Exception as exc`.
   On failure append `(record.id, "audit", str(exc))` to `report["errors"]` and
   continue with the next record.
5. Preserve all existing branch behavior in both functions, and keep the
   `Record`, `Entry`, `Backend` classes and both signatures.
6. Do not add new top-level functions, methods, classes, or lambdas. Keep the
   refactor inside `process` and `audit`; `tests_public.py` checks this.

The public tests are in `tests_public.py`. Edit `solution.py` in place.
'''

PUBLIC_TEMPLATE = '''"""Public tests for __TASK__."""

from __future__ import annotations

import unittest

from solution import Backend, Entry, Record, audit, process


class TwoFunctionPublicTests(unittest.TestCase):
    def test_process_empty_calls_notifier_once(self):
        calls = []
        report = process([], Backend({}), calls.append)
        self.assertEqual(report["matched"], 0)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["notified"], 1)
        self.assertEqual(len(calls), 1)

    def test_process_boom_does_not_abort(self):
        records = [Record("a", "alpha"), Record("boom", "alpha"), Record("b", "beta")]
        backend = Backend({"a": [Entry(1, 150)], "b": [Entry(2, 10)]})
        report = process(records, backend, lambda report: None)
        self.assertIn(("boom", "record", "backend unavailable"), report["errors"])
        self.assertGreaterEqual(report["matched"], 1)
        self.assertEqual(report["notified"], 1)

    def test_process_inactive_and_error_categories(self):
        records = [Record("x", "alpha", active=False), Record("a", "alpha")]
        backend = Backend({"a": [Entry(1, -5), Entry(2, 10, currency="EUR")]})
        report = process(records, backend, None)
        self.assertEqual(report["missing"], ["x"])
        self.assertIn(("a", 1, "amount"), report["errors"])
        self.assertIn(("a", 2, "currency"), report["errors"])
        self.assertEqual(report["notified"], 0)

    def test_audit_isolates_boom(self):
        records = [Record("a", "alpha"), Record("boom", "alpha"), Record("b", "beta")]
        backend = Backend({"a": [Entry(1, 150)], "b": [Entry(2, 10)]})
        report = audit(records, backend)
        self.assertIn(("boom", "audit", "backend unavailable"), report["errors"])
        self.assertGreaterEqual(report["matched"], 1)

    def test_structure(self):
        import ast
        import inspect
        import solution

        tree = ast.parse(inspect.getsource(solution))
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.FunctionDef)],
            ["process", "audit"],
        )
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.ClassDef)],
            ["Record", "Entry", "Backend"],
        )
        allowed = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("process", "audit"):
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

HIDDEN_TEMPLATE = '''"""Hidden differential tests for __TASK__."""

from __future__ import annotations

import copy
import unittest

from solution import Backend, Entry, Record, audit, process


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


class TwoFunctionHiddenTests(unittest.TestCase):
    def _check_process(self, records, data, use_notifier=True):
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

    def _check_audit(self, records, data):
        expected = reference_audit(records, Backend(data))
        actual = audit(records, Backend(data))
        self.assertEqual(actual, expected)

    def test_empty(self):
        self._check_process([], {}, True)
        self._check_process([], {}, False)
        self._check_audit([], {})

    def test_each_kind(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self._check_process([Record(kind, kind)], {kind: entries()}, True)
                self._check_process([Record(kind, kind)], {kind: entries()}, False)
                self._check_audit([Record(kind, kind)], {kind: entries()})

    def test_mixed(self):
        records = [Record(kind, kind) for kind in KINDS]
        records += [
            Record("inactive", "alpha", active=False),
            Record("unknown", "unknown"),
        ]
        data = {kind: entries() for kind in KINDS}
        self._check_process(records, data, True)
        self._check_process(records, data, False)
        self._check_audit(records, data)

    def test_boom_positions(self):
        base = [Record("a", "alpha"), Record("b", "beta")]
        data = {"a": entries(), "b": entries()}
        for index in range(len(base) + 1):
            records = base[:index] + [Record("boom", "alpha")] + base[index:]
            with self.subTest(index=index):
                self._check_process(records, data, True)
                self._check_audit(records, data)

    def test_structure(self):
        import ast
        import inspect
        import solution

        tree = ast.parse(inspect.getsource(solution))
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.FunctionDef)],
            ["process", "audit"],
        )
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.ClassDef)],
            ["Record", "Entry", "Backend"],
        )
        allowed = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("process", "audit"):
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


def audit_start(kinds: list[str]) -> str:
    return AUDIT_START.replace("__AUDIT_BRANCHES__", branch_block(kinds, 16))


def audit_reference(kinds: list[str]) -> str:
    return AUDIT_REFERENCE.replace("__AUDIT_BRANCHES__", branch_block(kinds, 20))


def build_task(task: str, kinds: list[str]) -> str:
    return TASK_TEMPLATE.replace("__TASK__", task).replace("__N__", str(len(kinds)))


def build_start_file(task: str, kinds: list[str]) -> str:
    return build_start(task, kinds) + "\n\n" + audit_start(kinds)


def build_reference_file(kinds: list[str]) -> str:
    return audit_reference(kinds)


def build_reference_solution_file(kinds: list[str]) -> str:
    process = build_reference_solution(kinds)
    audit = audit_reference(kinds).replace("def reference_audit(", "def audit(", 1)
    return process + "\n\n" + audit


def build_public(task: str) -> str:
    return PUBLIC_TEMPLATE.replace("__TASK__", task)


def build_hidden(task: str, kinds: list[str]) -> str:
    reference = build_reference(kinds) + "\n\n" + build_reference_file(kinds)
    return (
        HIDDEN_TEMPLATE.replace("__TASK__", task)
        .replace("__REFERENCE__", reference.rstrip())
        .replace("__KINDS__", repr(kinds))
    )


def write_task(task: str, kinds: list[str], reference_dir: Path) -> None:
    task_dir = BENCH / "tasks" / task
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.md").write_text(build_task(task, kinds), encoding="utf-8")
    (task_dir / "start.py").write_text(build_start_file(task, kinds), encoding="utf-8")
    (task_dir / "tests_public.py").write_text(build_public(task), encoding="utf-8")
    (BENCH / "hidden").mkdir(parents=True, exist_ok=True)
    (BENCH / "hidden" / f"{task}.py").write_text(build_hidden(task, kinds), encoding="utf-8")
    reference_dir.mkdir(parents=True, exist_ok=True)
    (reference_dir / f"{task}.py").write_text(
        build_reference_solution_file(kinds), encoding="utf-8"
    )


def validate(tasks: list[tuple[str, list[str]]], reference_dir: Path) -> bool:
    ok = True
    for task, _kinds in tasks:
        with tempfile.TemporaryDirectory(prefix="pyforai-calibrate-t-") as temp:
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
    parser.add_argument("--levels", default="4,8,12,16,20,24")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    counts = [int(part) for part in args.levels.split(",") if part.strip()]
    if any(count < 2 or count > len(KIND_ORDER) for count in counts):
        raise SystemExit(f"levels must be between 2 and {len(KIND_ORDER)}")

    reference_dir = BENCH / "calibrate" / "_reference"
    tasks: list[tuple[str, list[str]]] = []
    for index, count in enumerate(counts, start=1):
        task = f"T{index}_pipeline"
        kinds = KIND_ORDER[:count]
        write_task(task, kinds, reference_dir)
        tasks.append((task, kinds))
        print(f"generated {task}: {count} kinds, two functions")

    if args.validate and not validate(tasks, reference_dir):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
