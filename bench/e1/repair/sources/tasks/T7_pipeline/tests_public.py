"""Public tests for T7_pipeline."""

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
