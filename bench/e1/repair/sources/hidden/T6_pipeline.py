"""Hidden differential tests for T6_pipeline."""

from __future__ import annotations

import copy
import unittest

from solution import Backend, Entry, Record, audit, process


def reference_process(records, backend, notifier=None):
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
                    elif record.kind == "kind_17":
                        if entry.amount % 17 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod17"))
                    elif record.kind == "kind_18":
                        if entry.amount % 18 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod18"))
                    elif record.kind == "kind_19":
                        if entry.amount % 19 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod19"))
                    elif record.kind == "kind_20":
                        if entry.amount % 20 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod20"))
                    elif record.kind == "kind_21":
                        if entry.amount % 21 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod21"))
                    elif record.kind == "kind_22":
                        if entry.amount % 22 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod22"))
                    elif record.kind == "kind_23":
                        if entry.amount % 23 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod23"))
                    elif record.kind == "kind_24":
                        if entry.amount % 24 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod24"))
                    else:
                        report["errors"].append((record.id, entry.id, "kind"))
        except Exception as exc:
            report["errors"].append((record.id, "record", str(exc)))
    if notifier is not None:
        notifier(report)
        report["notified"] += 1
    return report


def reference_audit(records, backend):
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
                    elif record.kind == "kind_17":
                        if entry.amount % 17 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod17"))
                    elif record.kind == "kind_18":
                        if entry.amount % 18 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod18"))
                    elif record.kind == "kind_19":
                        if entry.amount % 19 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod19"))
                    elif record.kind == "kind_20":
                        if entry.amount % 20 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod20"))
                    elif record.kind == "kind_21":
                        if entry.amount % 21 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod21"))
                    elif record.kind == "kind_22":
                        if entry.amount % 22 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod22"))
                    elif record.kind == "kind_23":
                        if entry.amount % 23 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod23"))
                    elif record.kind == "kind_24":
                        if entry.amount % 24 == 0:
                            report["matched"] += 1
                        else:
                            report["errors"].append((record.id, entry.id, "mod24"))
                    else:
                        report["errors"].append((record.id, entry.id, "kind"))
        except Exception as exc:
            report["errors"].append((record.id, "audit", str(exc)))
    return report


KINDS = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 'iota', 'kappa', 'mu', 'nu', 'xi', 'omicron', 'pi', 'rho', 'kind_17', 'kind_18', 'kind_19', 'kind_20', 'kind_21', 'kind_22', 'kind_23', 'kind_24']


def entries():
    return [
        Entry(1, 150),
        Entry(2, 50),
        Entry(3, -1),
        Entry(4, 10, currency="EUR"),
        Entry(5, 50, status="skip"),
        Entry(6, 50, status="hold"),
        Entry(7, 2000),
        Entry(8, 10, status="new"),
        Entry(9, 10, status="ok"),
    ]


class TwoFunctionHiddenTests(unittest.TestCase):
    def _check_process(self, records, data, use_notifier=True):
        expected_calls = []
        actual_calls = []

        def expected_notifier(report):
            expected_calls.append(copy.deepcopy(report))

        def actual_notifier(report):
            actual_calls.append(copy.deepcopy(report))

        expected = reference_process(
            records,
            Backend(data),
            expected_notifier if use_notifier else None,
        )
        actual = process(
            records,
            Backend(data),
            actual_notifier if use_notifier else None,
        )
        self.assertEqual(actual, expected)
        self.assertEqual(actual_calls, expected_calls)

    def _check_audit(self, records, data):
        expected = reference_audit(records, Backend(data))
        actual = audit(records, Backend(data))
        self.assertEqual(actual, expected)

    def test_empty(self):
        self._check_process([], {}, True)
        self._check_process([], {}, False)
        self._check_audit([], {})

    def test_each_kind(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self._check_process([Record(kind, kind)], {kind: entries()}, True)
                self._check_process([Record(kind, kind)], {kind: entries()}, False)
                self._check_audit([Record(kind, kind)], {kind: entries()})

    def test_mixed(self):
        records = [Record(kind, kind) for kind in KINDS]
        records += [
            Record("inactive", "alpha", active=False),
            Record("unknown", "unknown"),
        ]
        data = {kind: entries() for kind in KINDS}
        self._check_process(records, data, True)
        self._check_process(records, data, False)
        self._check_audit(records, data)

    def test_boom_positions(self):
        base = [Record("a", "alpha"), Record("b", "beta")]
        data = {"a": entries(), "b": entries()}
        for index in range(len(base) + 1):
            records = base[:index] + [Record("boom", "alpha")] + base[index:]
            with self.subTest(index=index):
                self._check_process(records, data, True)
                self._check_audit(records, data)

    def test_structure(self):
        import ast
        import inspect
        import solution

        tree = ast.parse(inspect.getsource(solution))
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.FunctionDef)],
            ["process", "audit"],
        )
        self.assertEqual(
            [node.name for node in tree.body if isinstance(node, ast.ClassDef)],
            ["Record", "Entry", "Backend"],
        )
        allowed = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("process", "audit"):
                allowed.add(id(node))
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name in ("__init__", "get"):
                        allowed.add(id(child))
        extra = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and id(node) not in allowed
        ]
        self.assertEqual(extra, [])
        self.assertEqual([node for node in ast.walk(tree) if isinstance(node, ast.Lambda)], [])
