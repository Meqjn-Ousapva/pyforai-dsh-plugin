"""Deterministic E1 suite: does ``pyforai check`` catch structural drift?

For every corpus file we pick a few blocks, insert one anchor (the frozen
assertion), inject one syntax-valid drift, and record:

* whether ``py_compile`` accepts the result (it always should -- that is the
  point of the exercise),
* whether ``pyforai check`` reports an error, and which code,
* whether ``check --strict`` reports the deleted-anchor case (E010),
* how close the diagnostic line is to the injected drift.

The suite also records false positives on clean anchored files and the
formatter interaction (``pyforai fmt`` and, when available, ``black``).

Usage::

    python -m bench.e1.run_drift --quick
    python -m bench.e1.run_drift
    python -m bench.e1.run_drift --formatter black

Results go to ``bench/e1/drift/results``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .common import (
    E1,
    ROOT,
    anchor_fingerprint,
    check_source,
    compile_ok,
    diagnostic_codes,
    edit_payload_bytes,
    fmt_path_cli,
    git_diff_text,
    pyforai_version,
    read_json,
    run_command,
    sha256_file,
    sha256_text,
    write_json,
    write_text,
)
from .corpus import CorpusFile, load_corpus
from .drift import DRIFTS, DriftCase, InjectionError, code_drift_targets, enumerate_targets, make_case

RESULTS = E1 / "drift" / "results"
CASES = RESULTS / "cases"
DEPS = E1 / ".deps"
ERROR_CODES = {"E001", "E002", "E003", "E004", "E005", "E006", "E007", "E008"}


# ---------------------------------------------------------------------------
# formatter helpers


def black_version() -> Optional[str]:
    env = _deps_env()
    try:
        proc = run_command([sys.executable, "-m", "black", "--version"], env=env, timeout=30)
    except (OSError, Exception):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or proc.stderr).strip().splitlines()[0]


def _deps_env() -> dict[str, str]:
    env = os.environ.copy()
    if DEPS.exists():
        env["PYTHONPATH"] = str(DEPS) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def run_black(path: Path) -> tuple[bool, str]:
    env = _deps_env()
    try:
        proc = run_command(
            [sys.executable, "-m", "black", "--quiet", str(path)],
            env=env,
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001 - formatter is optional
        return False, f"{type(exc).__name__}: {exc}"
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-1000:]


def run_pyforai_fmt(path: Path) -> tuple[bool, str]:
    return fmt_path_cli(path, min_lines=5, min_depth=3)


# ---------------------------------------------------------------------------
# case evaluation


def _min_line_distance(result, lines: tuple[int, ...]) -> Optional[int]:
    error_lines = [d.lineno for d in result.errors if d.lineno]
    if not error_lines:
        return None
    return min(abs(error - line) for error in error_lines for line in lines if line)


def evaluate_case(case: DriftCase) -> dict:
    syntax_ok = compile_ok(case.source)
    normal = check_source(case.source)
    strict = check_source(case.source, strict=True)
    normal_codes = diagnostic_codes(normal)
    strict_codes = diagnostic_codes(strict)
    detected = any(code in ERROR_CODES for code in normal_codes)
    strict_detected = any(code in (ERROR_CODES | {"E010"}) for code in strict_codes)
    strict_e010 = "E010" in strict_codes
    expected_match = (
        all(code in normal_codes for code in case.expected_codes)
        if case.expected_codes
        else not detected
    )
    distance = _min_line_distance(normal, (case.anchor_line, case.drift_line))
    anchor_distance = _min_line_distance(normal, (case.anchor_line,))
    return {
        **case.as_dict(),
        "syntax_ok": syntax_ok,
        "detected": detected,
        "strict_detected": strict_detected,
        "strict_e010": strict_e010,
        "codes": normal_codes,
        "strict_codes": strict_codes,
        "expected_match": expected_match,
        "diagnostic_line_distance": distance,
        "anchor_line_distance": anchor_distance,
        "diagnostics": [d.as_dict() for d in normal.diagnostics],
    }


def collect_cases(
    corpus: list[CorpusFile],
    *,
    per_file_targets: int,
    per_class: int,
    per_file_per_class: int,
    max_files: Optional[int] = None,
) -> tuple[list[DriftCase], list[dict]]:
    cases: list[DriftCase] = []
    failures: list[dict] = []
    counts: Counter = Counter()
    per_file: Counter = Counter()
    for corpus_file in corpus[:max_files]:
        text = corpus_file.read()
        anchor_targets = enumerate_targets(text, corpus_file.id, per_file=per_file_targets)
        code_targets = code_drift_targets(text, corpus_file.id, per_file=per_file_targets)
        for target, drifts in (
            (anchor_targets, [d for d in DRIFTS if DRIFTS[d][0] != "code" or d == "not_adjacent"]),
            (code_targets, ["dedent_last", "consistent_shift"]),
        ):
            for block in target:
                for drift in drifts:
                    if counts[drift] >= per_class:
                        continue
                    if per_file[(corpus_file.id, drift)] >= per_file_per_class:
                        continue
                    try:
                        case = make_case(text, block, drift)
                    except InjectionError as exc:
                        failures.append(
                            {
                                "file": corpus_file.id,
                                "drift": drift,
                                "target": block.key,
                                "error": str(exc),
                            }
                        )
                        continue
                    if not compile_ok(case.source):
                        failures.append(
                            {
                                "file": corpus_file.id,
                                "drift": drift,
                                "target": block.key,
                                "error": "syntax error after injection",
                            }
                        )
                        continue
                    cases.append(case)
                    counts[drift] += 1
                    per_file[(corpus_file.id, drift)] += 1
    return cases, failures


# ---------------------------------------------------------------------------
# clean / formatter checks


def clean_checks(corpus: list[CorpusFile], cases: list[DriftCase]) -> tuple[list[dict], dict]:
    """Check the anchored file before drift; one row per unique (file,target)."""
    rows: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for case in cases:
        key = (case.file_id, case.target.lineno)
        if key in seen:
            continue
        seen.add(key)
        result = check_source(case.clean_source)
        rows.append(
            {
                "file": case.file_id,
                "target": case.target.key,
                "anchors": len(anchor_fingerprint(case.clean_source)),
                "errors": len(result.errors),
                "codes": diagnostic_codes(result),
            }
        )
    positives = sum(1 for row in rows if row["errors"] > 0)
    summary = {
        "clean_cases": len(rows),
        "clean_false_positives": positives,
        "clean_false_positive_rate": positives / len(rows) if rows else None,
    }
    return rows, summary


def formatter_checks(corpus: list[CorpusFile], *, use_black: bool) -> dict:
    """Run pyforai fmt (and optionally black) on each clean corpus file."""
    rows: list[dict] = []
    black = black_version() if use_black else None
    for corpus_file in corpus:
        with tempfile.TemporaryDirectory(prefix="e1-fmt-") as tmp:
            path = Path(tmp) / "file.py"
            path.write_text(corpus_file.read(), encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            fmt_ok, fmt_output = run_pyforai_fmt(path)
            after_fmt = path.read_text(encoding="utf-8")
            anchors = len(anchor_fingerprint(after_fmt))
            fmt_check = check_source(after_fmt)
            fmt_strict = check_source(after_fmt, strict=True) if fmt_ok else None
            # Idempotency: a second fmt on a changed file must not change it.
            fmt2_ok, _ = run_pyforai_fmt(path)
            after_fmt2 = path.read_text(encoding="utf-8")
            idempotent = after_fmt == after_fmt2
            black_ok = None
            black_error = ""
            check_after_black = None
            anchors_after_black = None
            if black and fmt_ok:
                black_ok, black_error = run_black(path)
                after_black = path.read_text(encoding="utf-8")
                anchors_after_black = len(anchor_fingerprint(after_black))
                check_after_black = check_source(after_black)
            rows.append(
                {
                    "file": corpus_file.id,
                    "lines": corpus_file.lines,
                    "fmt_ok": fmt_ok,
                    "fmt_output": fmt_output,
                    "fmt_anchors": anchors,
                    "fmt_check_ok": fmt_check.ok,
                    "fmt_check_errors": len(fmt_check.errors),
                    "fmt_check_ok_given_ok": fmt_check.ok if fmt_ok else None,
                    "fmt_strict_ok": fmt_strict.ok if fmt_strict is not None else None,
                    "fmt_strict_errors": len(fmt_strict.errors) if fmt_strict is not None else None,
                    "fmt_idempotent": idempotent,
                    "black_ok": black_ok,
                    "black_error": black_error[-500:] if black_error else "",
                    "check_after_black_ok": check_after_black.ok if check_after_black else None,
                    "black_anchors": anchors_after_black,
                }
            )
    return {
        "pyforai_version": pyforai_version(),
        "black_version": black,
        "rows": rows,
        "fmt_ok": sum(1 for row in rows if row["fmt_ok"]),
        "fmt_check_ok": sum(1 for row in rows if row["fmt_check_ok"]),
        "fmt_strict_ok": sum(1 for row in rows if row["fmt_strict_ok"]),
        "fmt_idempotent": sum(1 for row in rows if row["fmt_idempotent"]),
        "fmt_check_ok_given_ok": sum(1 for row in rows if row["fmt_check_ok_given_ok"]),
        "fmt_strict_ok_given_ok": sum(1 for row in rows if row["fmt_ok"] and row["fmt_strict_ok"]),
        "fmt_failures": [
            {"file": row["file"], "output": row["fmt_output"]} for row in rows if not row["fmt_ok"]
        ],
        "black_ok": sum(1 for row in rows if row["black_ok"]),
        "check_after_black_ok": sum(1 for row in rows if row["check_after_black_ok"]),
    }


def black_on_cases(cases: list[DriftCase], sample_per_drift: int = 3) -> list[dict]:
    """Does black preserve, fix, or mask the injected drift?"""
    rows: list[dict] = []
    seen: Counter = Counter()
    for case in cases:
        if seen[case.drift] >= sample_per_drift:
            continue
        seen[case.drift] += 1
        with tempfile.TemporaryDirectory(prefix="e1-black-") as tmp:
            path = Path(tmp) / "case.py"
            path.write_text(case.source, encoding="utf-8")
            before_ast = _ast_dump(case.source)
            ok, error = run_black(path)
            after = path.read_text(encoding="utf-8")
            after_ast = _ast_dump(after)
            before_result = check_source(case.source)
            result = check_source(after)
            before = any(code in ERROR_CODES for code in diagnostic_codes(before_result))
            after_detected = any(code in ERROR_CODES for code in diagnostic_codes(result))
            rows.append(
                {
                    "case_id": case.case_id,
                    "drift": case.drift,
                    "black_ok": ok,
                    "black_error": error[-500:] if error else "",
                    "ast_changed": before_ast != after_ast,
                    "detected_before": before,
                    "detected_after_black": after_detected,
                    "masked": before and not after_detected,
                    "codes_after_black": diagnostic_codes(result),
                }
            )
    return rows


def _ast_dump(text: str) -> str:
    import ast

    try:
        return ast.dump(ast.parse(text), include_attributes=False)
    except SyntaxError:
        return "SYNTAX_ERROR"


# ---------------------------------------------------------------------------
# reporting


def _mean(values: list[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def build_summary(cases: list[dict], clean: dict, formatter: dict, black_cases: list[dict], failures: list[dict]) -> dict:
    by_drift: dict[str, dict] = {}
    for drift in DRIFTS:
        group = [case for case in cases if case["drift"] == drift]
        if not group:
            continue
        expected = [case for case in group if case["expect_detect"]]
        detected = [case for case in expected if case["detected"]]
        strict_expected = [case for case in group if case["expect_strict"]]
        strict_detected = [case for case in strict_expected if case["strict_detected"]]
        distances = [case["diagnostic_line_distance"] for case in detected if case["diagnostic_line_distance"] is not None]
        by_drift[drift] = {
            "n": len(group),
            "expected_detect": len(expected),
            "detected": len(detected),
            "detection_rate": len(detected) / len(expected) if expected else None,
            "strict_expected": len(strict_expected),
            "strict_detected": len(strict_detected),
            "strict_rate": len(strict_detected) / len(strict_expected) if strict_expected else None,
            "mean_line_distance": _mean(distances),
            "codes": dict(Counter(code for case in group for code in case["codes"])),
            "expected_match": sum(1 for case in group if case["expected_match"]),
        }
    expected = [case for case in cases if case["expect_detect"]]
    detected = [case for case in expected if case["detected"]]
    strict_expected = [case for case in cases if case["expect_strict"]]
    strict_detected = [case for case in strict_expected if case["strict_detected"]]
    by_file: dict[str, dict] = {}
    for case in cases:
        row = by_file.setdefault(case["file_id"], {"n": 0, "detected": 0, "expected": 0})
        row["n"] += 1
        if case["expect_detect"]:
            row["expected"] += 1
            row["detected"] += int(case["detected"])
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cases": len(cases),
        "files": len(by_file),
        "detection": {
            "expected": len(expected),
            "detected": len(detected),
            "rate": len(detected) / len(expected) if expected else None,
        },
        "strict": {
            "expected": len(strict_expected),
            "detected": len(strict_detected),
            "rate": len(strict_detected) / len(strict_expected) if strict_expected else None,
        },
        "expected_match": sum(1 for case in cases if case["expected_match"]),
        "expected_match_rate": (
            sum(1 for case in cases if case["expected_match"]) / len(cases) if cases else None
        ),
        "by_drift": by_drift,
        "by_file": by_file,
        "clean": clean,
        "formatter": formatter,
        "black_cases": black_cases,
        "injection_failures": failures,
    }


def render_report(summary: dict) -> str:
    lines = [
        "# E1 drift report",
        "",
        f"Generated: {summary['generated']}",
        "",
        "## Headline",
        "",
        f"- Cases: **{summary['cases']}** across **{summary['files']}** files.",
        f"- Check detection: **{summary['detection']['detected']}/{summary['detection']['expected']}** "
        f"({_pct(summary['detection']['rate'])}) of syntax-valid drifts.",
        f"- Strict-mode detection: **{summary['strict']['detected']}/{summary['strict']['expected']}** "
        f"({_pct(summary['strict']['rate'])}), including deleted anchors (E010).",
        f"- Expected diagnostic matched: **{summary['expected_match']}/{summary['cases']}** "
        f"({_pct(summary['expected_match_rate'])}).",
        f"- Clean-file false positives: **{summary['clean']['clean_false_positives']}/"
        f"{summary['clean']['clean_cases']}**.",
        "",
        "`py_compile` accepts 100% of these cases by construction; the comparison is",
        "the point: every drift below is syntax-valid Python that a test-free",
        "syntax check cannot see.",
        "",
        "## By drift class",
        "",
        "| drift | n | detected | rate | strict | mean diag distance | codes |",
        "|---|---|---|---|---|---|---|",
    ]
    for drift, row in summary["by_drift"].items():
        lines.append(
            "| {drift} | {n} | {detected}/{expected} | {rate} | {strict}/{strict_expected} | {distance} | {codes} |".format(
                drift=drift,
                n=row["n"],
                detected=row["detected"],
                expected=row["expected_detect"],
                rate=_pct(row["detection_rate"]),
                strict=row["strict_detected"],
                strict_expected=row["strict_expected"],
                distance=_fmt(row["mean_line_distance"]),
                codes=", ".join(f"{code}:{count}" for code, count in sorted(row["codes"].items())) or "—",
            )
        )
    fmt = summary["formatter"]
    total_files = len(fmt["rows"])
    lines += [
        "",
        "## Formatter interaction",
        "",
        "| metric | value |",
        "|---|---|",
        "| pyforai | {} |".format(fmt.get("pyforai_version") or "unknown"),
        "| files | {} |".format(total_files),
        "| `pyforai fmt` exit 0 | {} |".format(fmt["fmt_ok"]),
        "| ... and result passes check | {} |".format(fmt["fmt_check_ok_given_ok"]),
        "| ... and result passes strict | {} |".format(fmt["fmt_strict_ok_given_ok"]),
        "| second `pyforai fmt` is idempotent | {} |".format(fmt["fmt_idempotent"]),
        "| black available | {} |".format(fmt["black_version"] or "no"),
        "| black exit 0 (after successful fmt) | {} |".format(fmt["black_ok"]),
        "| check passes after black | {} |".format(fmt["check_after_black_ok"]),
        "",
        "`fmt` inserts derived anchors.  A file that `fmt` cannot process is a",
        "tool failure, not a drift detection result; the rows above separate it.",
        "",
    ]
    if fmt["fmt_failures"]:
        lines += ["### `fmt` failures", ""]
        for failure in fmt["fmt_failures"]:
            detail = " ".join(failure["output"].split())[:240]
            lines.append(f"- `{failure['file']}`: {detail}")
        lines.append("")
    lines += [
        "## Black on drifted cases",
        "",
        "| drift | n | ast changed | detected before | still detected | masked by black |",
        "|---|---|---|---|---|---|",
    ]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in summary["black_cases"]:
        grouped[row["drift"]].append(row)
    for drift, rows in grouped.items():
        lines.append(
            f"| {drift} | {len(rows)} | {sum(1 for r in rows if r['ast_changed'])} | "
            f"{sum(1 for r in rows if r['detected_before'])} | "
            f"{sum(1 for r in rows if r['detected_after_black'])} | "
            f"{sum(1 for r in rows if r['masked'])} |"
        )
    lines += [
        "",
        "## Injection failures",
        "",
        f"{len(summary['injection_failures'])} attempted (block, drift) pairs could not be",
        "injected without a syntax error or without producing the expected code.",
        "These are generator coverage limits, not checker results.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f}"


# ---------------------------------------------------------------------------
# main


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="6 files, 20 cases per class")
    parser.add_argument("--formatter", default="black", choices=("black", "none"))
    parser.add_argument("--per-file-targets", type=int, default=12)
    parser.add_argument("--per-class", type=int, default=60)
    parser.add_argument("--per-file-per-class", type=int, default=3)
    parser.add_argument("--max-files", type=int, default=None)
    args = parser.parse_args(argv)

    corpus = load_corpus()
    if args.quick:
        corpus = corpus[:6]
        args.per_class = min(args.per_class, 20)
        args.per_file_targets = min(args.per_file_targets, 8)
    if args.max_files:
        corpus = corpus[: args.max_files]

    RESULTS.mkdir(parents=True, exist_ok=True)
    CASES.mkdir(parents=True, exist_ok=True)
    started = time.time()
    print(f"corpus: {len(corpus)} files")
    cases, failures = collect_cases(
        corpus,
        per_file_targets=args.per_file_targets,
        per_class=args.per_class,
        per_file_per_class=args.per_file_per_class,
    )
    print(f"cases: {len(cases)}; injection failures: {len(failures)}")

    evaluated = []
    for index, case in enumerate(cases, 1):
        evaluated.append(evaluate_case(case))
        if index % 50 == 0:
            print(f"  evaluated {index}/{len(cases)}")
    clean_rows, clean_summary = clean_checks(corpus, cases)
    formatter = formatter_checks(corpus, use_black=args.formatter == "black")
    black_cases = black_on_cases(cases) if args.formatter == "black" else []
    summary = build_summary(evaluated, clean_summary, formatter, black_cases, failures)

    # Persist every case as a file so a surprising result can be inspected.
    for row in evaluated:
        path = CASES / f"{row['case_id']}.py"
        case = next(c for c in cases if c.case_id == row["case_id"])
        write_text(path, case.source)
        row["path"] = str(path.relative_to(E1))
    with (RESULTS / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for row in evaluated:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(RESULTS / "clean.json", clean_rows)
    write_json(RESULTS / "formatter.json", formatter)
    write_json(RESULTS / "summary.json", summary)
    write_text(RESULTS / "report.md", render_report(summary))
    elapsed = time.time() - started
    print(f"wrote {RESULTS / 'report.md'} ({elapsed:.1f}s)")
    print(
        f"detection {summary['detection']['detected']}/{summary['detection']['expected']} "
        f"({_pct(summary['detection']['rate'])}); "
        f"clean FP {summary['clean']['clean_false_positives']}/{summary['clean']['clean_cases']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
