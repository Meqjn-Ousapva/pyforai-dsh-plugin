"""Public tests for E1.1 single-function process."""

from __future__ import annotations

import unittest

from solution import Backend, Entry, Record, process


class PublicTests(unittest.TestCase):
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
