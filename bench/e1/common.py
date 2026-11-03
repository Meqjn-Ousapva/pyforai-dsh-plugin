"""Shared helpers for the E1 bench.

The E1 harness is deliberately small: it prepares files, runs deterministic
checks, scores artifacts, and aggregates.  It never calls an LLM itself; a run
is produced by an external agent that only sees its own run directory.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

E1 = Path(__file__).resolve().parent
BENCH = E1.parent
ROOT = BENCH.parent

sys.path.insert(0, str(ROOT))

from pyforai import check_source  # noqa: E402
from pyforai.anchors import ANCHOR_RE, build_model  # noqa: E402

KINDS = ("if", "for", "while", "try", "with", "def", "class", "match")


def pyforai_argv() -> list[str]:
    """The product CLI to measure.

    Prefer the installed binary (the same one the DSH plugin ships), because
    the Go and Python implementations can diverge.  Set ``PYFORAI_BIN`` to
    override; fall back to the in-tree Python module for a source-only run.
    """
    configured = os.environ.get("PYFORAI_BIN")
    if configured:
        return [configured]
    found = shutil.which("pyforai")
    if found:
        return [found]
    return [sys.executable, "-m", "pyforai"]


def pyforai_version() -> str:
    try:
        proc = run_command(pyforai_argv() + ["--version"], timeout=10)
    except Exception:  # noqa: BLE001
        return "unknown"
    return (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr) else "unknown"


def check_path_cli(path: Path, *, strict: bool = False) -> dict:
    """Run ``pyforai check --json`` on one path and return a small dict."""
    argv = pyforai_argv() + ["check", "--json"]
    if strict:
        argv.append("--strict")
    argv.append(str(path))
    try:
        proc = run_command(argv, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "errors": 1, "diagnostics": [{"code": "CLI", "line": 0, "message": str(exc)}], "raw": ""}
    raw = proc.stdout or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "errors": 1, "diagnostics": [{"code": "CLI", "line": 0, "message": (proc.stderr or raw)[:1000]}], "raw": raw}
    files = data.get("files") or []
    diagnostics = []
    for entry in files:
        diagnostics.extend(entry.get("diagnostics") or [])
    return {
        "ok": bool(data.get("ok", not diagnostics)),
        "errors": int(data.get("errors", sum(1 for d in diagnostics if d.get("code") != "E010"))),
        "diagnostics": diagnostics,
        "raw": raw,
    }


def fmt_path_cli(path: Path, *, min_lines: int = 5, min_depth: int = 3, all_blocks: bool = False) -> tuple[bool, str]:
    argv = pyforai_argv() + ["fmt", "--min-lines", str(min_lines), "--min-depth", str(min_depth)]
    if all_blocks:
        argv.append("--all")
    argv.append(str(path))
    try:
        proc = run_command(argv, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_task_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def anchor_fingerprint(text: str) -> tuple[tuple[int, str], ...]:
    """A position-independent fingerprint of every anchor line.

    Line numbers shift when code above them changes.  What must not change is
    the sequence of (indentation, anchor text).  This catches edits, deletions,
    and re-indentation of anchors while allowing normal code edits.
    """
    result: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = ANCHOR_RE.search(line)
        if not match:
            continue
        stripped = line.lstrip(" \t")
        result.append((len(line) - len(stripped), stripped.strip()))
    return tuple(result)


def anchor_count(text: str) -> int:
    return len(anchor_fingerprint(text))


def ast_fingerprint(text: str) -> str:
    """Semantic fingerprint: AST without line/column attributes."""
    return ast.dump(ast.parse(text), include_attributes=False)


def compile_ok(text: str, filename: str = "<case>") -> bool:
    try:
        compile(text, filename, "exec")
        return True
    except (SyntaxError, ValueError):
        return False


def check_text(text: str, filename: str = "<case>", *, strict: bool = False,
               min_lines: int = 5, min_depth: int = 3):
    return check_source(
        text,
        filename,
        strict=strict,
        min_lines=min_lines,
        min_depth=min_depth,
    )


def diagnostic_codes(result) -> list[str]:
    return sorted({d.code for d in result.diagnostics})


def first_error_line(result) -> Optional[int]:
    for diagnostic in result.diagnostics:
        if diagnostic.severity == "error":
            return diagnostic.lineno
    return None


def run_command(
    argv: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout: float = 120.0,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def git_diff_text(old: str, new: str, old_name: str = "a", new_name: str = "b") -> str:
    import difflib

    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=old_name,
            tofile=new_name,
        )
    )


def edit_payload_bytes(old: str, new: str) -> int:
    """Bytes the model had to produce for this edit.

    This is a proxy for output tokens on repair tasks: sum of added/removed
    line lengths in a unified diff, excluding file headers.  It is not a token
    count, but it is monotone with the amount of text re-emitted.
    """
    total = 0
    for line in git_diff_text(old, new).splitlines():
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith(("+", "-")):
            total += len(line) + 1
    return total


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def parse_epoch(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def count_log_failures(path: Path) -> tuple[Optional[int], Optional[int]]:
    if not path.exists():
        return None, None
    try:
        lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return None, None
    failures = sum(1 for line in lines if re.search(r"\bfail\b", line, re.IGNORECASE))
    return len(lines), failures


def count_check_calls(path: Path) -> tuple[int, int, int]:
    """Return (check calls, pyforai calls, help calls) from commands.log."""
    if not path.exists():
        return 0, 0, 0
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    pyforai = [line for line in lines if "pyforai" in line]
    checks = [line for line in pyforai if re.search(r"\bcheck\b", line)]
    help_calls = [line for line in pyforai if "--help" in line or " -h" in line]
    return len(checks), len(pyforai), len(help_calls)


def tree_shape(text: str) -> dict:
    """Coarse shape counters used only for reporting, not for scoring."""
    tree = ast.parse(text)
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        name = type(node).__name__
        counts[name] = counts.get(name, 0) + 1
    return {
        "functions": sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
        "classes": sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef)),
        "blocks": len(build_model(text).blocks),
        "max_depth": _max_depth(tree),
        "nodes": counts,
    }


def _max_depth(node: ast.AST, depth: int = 0) -> int:
    from pyforai.anchors import kind_of

    if kind_of(node) is not None:
        depth += 1
    best = depth
    for child in ast.iter_child_nodes(node):
        best = max(best, _max_depth(child, depth))
    return best
