"""Pipeline calibration task T1_pipeline (4 record kinds)."""

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
                    if record.kind == "alpha":
                        if entry.amount > 100:
                            report["matched"] += 2
                        else:
                            report["matched"] += 1
                    elif record.kind == "beta":
                        if entry.status == "ok":
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    elif record.kind == "gamma":
                        if entry.amount % 2 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "parity"))
                    elif record.kind == "delta":
                        if entry.amount >= 50:
                            report["matched"] += 3
                        else:
                            report["matched"] += 1
                    else:
                        report["errors"].append((record.id, entry.id, "kind"))
            if notifier is not None:
                notifier(record.id, report)
                report["notified"] += 1
    return report


def audit(records, backend):
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
                if record.kind == "alpha":
                    if entry.amount > 100:
                        report["matched"] += 2
                    else:
                        report["matched"] += 1
                elif record.kind == "beta":
                    if entry.status == "ok":
                        report["matched"] += 1
                    else:
                        report["errors"].append((record.id, entry.id, "status"))
                elif record.kind == "gamma":
                    if entry.amount % 2 == 0:
                        report["matched"] += 1
                    else:
                        report["errors"].append((record.id, entry.id, "parity"))
                elif record.kind == "delta":
                    if entry.amount >= 50:
                        report["matched"] += 3
                    else:
                        report["matched"] += 1
                else:
                    report["errors"].append((record.id, entry.id, "kind"))
    return report
