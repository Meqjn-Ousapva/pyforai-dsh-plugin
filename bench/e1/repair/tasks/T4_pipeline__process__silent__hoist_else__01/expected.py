"""Pipeline calibration task reference (16 record kinds)."""

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
                    elif record.kind == "epsilon":
                        if entry.status in ("ok", "new"):
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    elif record.kind == "zeta":
                        if entry.amount > 1000:
                            report["errors"].append((record.id, entry.id, "limit"))
                        else:
                            report["matched"] += 1
                    elif record.kind == "eta":
                        if entry.status == "ok":
                            if entry.amount > 10:
                                report["matched"] += 2
                            else:
                                report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    elif record.kind == "theta":
                        report["matched"] += 4
                    elif record.kind == "iota":
                        if entry.status == "hold":
                            report["errors"].append((record.id, entry.id, "hold"))
                        else:
                            report["matched"] += 1
                    elif record.kind == "kappa":
                        if entry.amount > 500:
                            report["matched"] += 2
                        else:
                            report["matched"] += 1
                    elif record.kind == "mu":
                        if entry.status == "new":
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    elif record.kind == "nu":
                        if entry.amount > 200:
                            report["matched"] += 2
                        elif entry.amount > 50:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "small"))
                    elif record.kind == "xi":
                        if entry.status == "ok" and entry.amount > 100:
                            report["matched"] += 2
                        else:
                            report["matched"] += 1
                    elif record.kind == "omicron":
                        report["matched"] += 1
                    elif record.kind == "pi":
                        if entry.amount % 3 == 0:
                            report["matched"] += 2
                        else:
                            report["errors"].append((record.id, entry.id, "mod3"))
                    elif record.kind == "rho":
                        if entry.status == "ok":
                            if entry.amount > 1000:
                                report["errors"].append((record.id, entry.id, "limit"))
                            else:
                                report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    else:
                        report["errors"].append((record.id, entry.id, "kind"))
        except Exception as exc:
            report["errors"].append((record.id, "record", str(exc)))
    if notifier is not None:
        notifier(report)
        report["notified"] += 1
    return report


def audit(records, backend):
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
                    elif record.kind == "epsilon":
                        if entry.status in ("ok", "new"):
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    elif record.kind == "zeta":
                        if entry.amount > 1000:
                            report["errors"].append((record.id, entry.id, "limit"))
                        else:
                            report["matched"] += 1
                    elif record.kind == "eta":
                        if entry.status == "ok":
                            if entry.amount > 10:
                                report["matched"] += 2
                            else:
                                report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    elif record.kind == "theta":
                        report["matched"] += 4
                    elif record.kind == "iota":
                        if entry.status == "hold":
                            report["errors"].append((record.id, entry.id, "hold"))
                        else:
                            report["matched"] += 1
                    elif record.kind == "kappa":
                        if entry.amount > 500:
                            report["matched"] += 2
                        else:
                            report["matched"] += 1
                    elif record.kind == "mu":
                        if entry.status == "new":
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    elif record.kind == "nu":
                        if entry.amount > 200:
                            report["matched"] += 2
                        elif entry.amount > 50:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "small"))
                    elif record.kind == "xi":
                        if entry.status == "ok" and entry.amount > 100:
                            report["matched"] += 2
                        else:
                            report["matched"] += 1
                    elif record.kind == "omicron":
                        report["matched"] += 1
                    elif record.kind == "pi":
                        if entry.amount % 3 == 0:
                            report["matched"] += 2
                        else:
                            report["errors"].append((record.id, entry.id, "mod3"))
                    elif record.kind == "rho":
                        if entry.status == "ok":
                            if entry.amount > 1000:
                                report["errors"].append((record.id, entry.id, "limit"))
                            else:
                                report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "status"))
                    else:
                        report["errors"].append((record.id, entry.id, "kind"))
        except Exception as exc:
            report["errors"].append((record.id, "audit", str(exc)))
    return report
