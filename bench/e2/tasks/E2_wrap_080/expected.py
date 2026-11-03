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
            report["trace"].append(20)
            report["trace"].append(21)
            report["trace"].append(22)
            report["trace"].append(23)
            report["trace"].append(24)
            report["trace"].append(25)
            report["trace"].append(26)
            report["trace"].append(27)
            report["trace"].append(28)
            report["trace"].append(29)
            report["trace"].append(30)
            report["trace"].append(31)
            report["trace"].append(32)
            report["trace"].append(33)
            report["trace"].append(34)
            report["trace"].append(35)
            report["trace"].append(36)
            report["trace"].append(37)
            report["trace"].append(38)
            report["trace"].append(39)
            report["trace"].append(40)
            report["trace"].append(41)
            report["trace"].append(42)
            report["trace"].append(43)
            report["trace"].append(44)
            report["trace"].append(45)
            report["trace"].append(46)
            report["trace"].append(47)
            report["trace"].append(48)
            report["trace"].append(49)
            report["trace"].append(50)
            report["trace"].append(51)
            report["trace"].append(52)
            report["trace"].append(53)
            report["trace"].append(54)
            report["trace"].append(55)
            report["trace"].append(56)
            report["trace"].append(57)
            report["trace"].append(58)
            report["trace"].append(59)
            report["trace"].append(60)
            report["trace"].append(61)
            report["trace"].append(62)
            report["trace"].append(63)
            report["trace"].append(64)
            report["trace"].append(65)
            report["trace"].append(66)
            report["trace"].append(67)
            report["trace"].append(68)
            report["trace"].append(69)
            report["trace"].append(70)
            report["trace"].append(71)
            report["trace"].append(72)
            report["trace"].append(73)
            report["trace"].append(74)
            report["trace"].append(75)
            report["trace"].append(76)
            report["trace"].append(77)
            report["trace"].append(78)
            report["trace"].append(79)
    except Exception as exc:
        report["errors"].append((record.id, str(exc)))
    return report
