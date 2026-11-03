from __future__ import annotations


class Record:
    def __init__(self, id, kind="ok", fail=False):
        self.id = id
        self.kind = kind
        self.fail = fail


def process(records):
    report = {"ok": 0, "errors": [], "trace": []}
    try:
        for record in records:
            if record.kind == "skip":
                continue
            if record.fail:
                raise ValueError("boom")
            report["ok"] += 1
            report["trace"].append(record.id)
            report["trace"].append(0)
            report["trace"].append(1)
            report["trace"].append(2)
            report["trace"].append(3)
            report["trace"].append(4)
            report["trace"].append(5)
            report["trace"].append(6)
            report["trace"].append(7)
            report["trace"].append(8)
            report["trace"].append(9)
            report["trace"].append(10)
            report["trace"].append(11)
            report["trace"].append(12)
            report["trace"].append(13)
            report["trace"].append(14)
            report["trace"].append(15)
            report["trace"].append(16)
            report["trace"].append(17)
            report["trace"].append(18)
            report["trace"].append(19)
    except Exception as exc:
        report["errors"].append((record.id, str(exc)))
    return report
