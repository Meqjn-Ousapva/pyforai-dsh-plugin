"""The code to refactor for task R2."""

from __future__ import annotations


class Account:
    def __init__(self, id, active=True, currency="USD"):
        self.id = id
        self.active = active
        self.currency = currency


class Entry:
    def __init__(self, id, amount, currency="USD"):
        self.id = id
        self.amount = amount
        self.currency = currency


class Ledger:
    def __init__(self, entries):
        self.entries = entries

    def get(self, account_id):
        if account_id == "boom":
            raise RuntimeError("ledger unavailable")
        return self.entries.get(account_id, [])


def reconcile(accounts, ledger):
    report = {"matched": 0, "missing": [], "errors": []}
    for account in accounts:
        if account.active:
            for entry in ledger.get(account.id):
                if entry.amount > 0:
                    if entry.currency == account.currency:
                        report["matched"] += 1
                    else:
                        report["errors"].append((account.id, entry.id, "currency"))
                else:
                    report["errors"].append((account.id, entry.id, "amount"))
        else:
            report["missing"].append(account.id)
    return report
