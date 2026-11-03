"""Public tests for task R2 (per-account error isolation)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from solution import Account, Entry, Ledger, reconcile


class ReconcilePublicTests(unittest.TestCase):
    def test_failure_does_not_abort_others(self) -> None:
        accounts = [Account("a"), Account("boom"), Account("c")]
        ledger = Ledger({"a": [Entry(1, 10)], "c": [Entry(3, 30)]})
        report = reconcile(accounts, ledger)
        self.assertEqual(report["matched"], 2)
        self.assertIn(("boom", "account", "ledger unavailable"), report["errors"])
        self.assertEqual(report["missing"], [])

    def test_inactive_accounts_still_missing(self) -> None:
        accounts = [Account("a", active=False), Account("b")]
        ledger = Ledger({"b": [Entry(1, 5)]})
        report = reconcile(accounts, ledger)
        self.assertEqual(report["missing"], ["a"])
        self.assertEqual(report["matched"], 1)

    def test_existing_error_categories(self) -> None:
        accounts = [Account("a", currency="USD")]
        ledger = Ledger({"a": [Entry(1, 10, "EUR"), Entry(2, -1, "USD")]})
        report = reconcile(accounts, ledger)
        self.assertIn(("a", 1, "currency"), report["errors"])
        self.assertIn(("a", 2, "amount"), report["errors"])
        self.assertEqual(report["matched"], 0)


if __name__ == "__main__":
    unittest.main()
