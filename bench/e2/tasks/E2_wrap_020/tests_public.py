"""Public tests for E2 forced-reindent wrap."""

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
