"""Hidden tests for task R2 (per-account error isolation)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from solution import Account, Entry, Ledger, reconcile


class ReconcileHiddenTests(unittest.TestCase):
    def test_first_account_failure_then_success(self) -> None:
        accounts = [Account("boom"), Account("a")]
        ledger = Ledger({"a": [Entry(1, 1)]})
        report = reconcile(accounts, ledger)
        self.assertEqual(report["matched"], 1)
        self.assertIn(("boom", "account", "ledger unavailable"), report["errors"])

    def test_error_tuple_shape(self) -> None:
        report = reconcile([Account("boom")], Ledger({}))
        self.assertEqual(len(report["errors"]), 1)
        account_id, category, message = report["errors"][0]
        self.assertEqual(account_id, "boom")
        self.assertEqual(category, "account")
        self.assertEqual(message, "ledger unavailable")

    def test_multiple_failures_are_each_recorded(self) -> None:
        report = reconcile([Account("boom"), Account("boom")], Ledger({}))
        self.assertEqual(len(report["errors"]), 2)
        for entry in report["errors"]:
            self.assertEqual(entry[1], "account")

    def test_matches_before_failure_are_kept(self) -> None:
        accounts = [Account("a"), Account("boom")]
        ledger = Ledger({"a": [Entry(1, 1), Entry(2, 2)]})
        report = reconcile(accounts, ledger)
        self.assertEqual(report["matched"], 2)
        self.assertIn(("boom", "account", "ledger unavailable"), report["errors"])


if __name__ == "__main__":
    unittest.main()
