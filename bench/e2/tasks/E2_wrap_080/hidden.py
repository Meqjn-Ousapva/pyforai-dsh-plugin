"""Hidden tests for E2 forced-reindent wrap."""

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
