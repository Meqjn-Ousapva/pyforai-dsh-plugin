#!/usr/bin/env python3
"""Parity check: compare the Go binary's `check --json` with the Python one.

This is a development tool, not part of the shipped binary.  It walks the
project corpus (examples, the Python implementation, tests, bench tasks and
bench run artifacts), runs both checkers, and compares the diagnostic
(code, line, column) sets.

Usage:
    python3 go/oracle_check.py [--verbose]
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GO_BIN = ROOT / "bin" / "pyforai"
SEARCH_DIRS = ["examples", "pyforai", "tests", "bench/tasks", "bench/hidden", "bench/runs"]


def collect() -> list[pathlib.Path]:
    files: set[pathlib.Path] = set()
    for directory in SEARCH_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts or "go" in path.parts:
                continue
            files.add(path)
    return sorted(files)


def run_checker(command: list[str], path: pathlib.Path) -> dict:
    proc = subprocess.run(
        command + ["check", "--json", str(path.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.stdout.strip():
        return json.loads(proc.stdout)
    raise RuntimeError(f"{' '.join(command)} failed for {path}: {proc.stderr[:400]}")


def diagnostics(payload: dict) -> list[tuple[str, int, int]]:
    files = payload.get("files") or []
    if not files:
        return []
    return sorted(
        (d["code"], d["line"], d["col"])
        for d in (files[0].get("diagnostics") or [])
    )


def main() -> int:
    verbose = "--verbose" in sys.argv[1:]
    if not GO_BIN.exists():
        raise SystemExit(f"missing {GO_BIN}; run `make build` first")

    files = collect()
    differences = 0
    for path in files:
        python_payload = run_checker([sys.executable, "-m", "pyforai"], path)
        go_payload = run_checker([str(GO_BIN)], path)
        python_diag = diagnostics(python_payload)
        go_diag = diagnostics(go_payload)
        if python_payload.get("ok") != go_payload.get("ok") or python_diag != go_diag:
            differences += 1
            print(f"DIFF {path.relative_to(ROOT)}")
            print(f"  python: ok={python_payload.get('ok')} {python_diag}")
            print(f"  go    : ok={go_payload.get('ok')} {go_diag}")
        elif verbose:
            print(f"ok {path.relative_to(ROOT)}")

    print(f"checked {len(files)} files, {differences} differences")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
