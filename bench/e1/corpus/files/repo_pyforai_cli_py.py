"""Command-line interface.

Commands
--------
check          L1: validate every anchor, optionally enforce coverage
fmt            insert missing anchors (derived, not assertions)
wrap           L2: wrap a block in try/if/with/for/while
replace-body   L2: replace a block's body with auto-indented code
move           L2: move a block before/after/into another block

All editing commands validate the result and write atomically.  ``--json``
returns structured output for agent/tool integration.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tokenize
from pathlib import Path
from typing import Iterable, Optional

from . import __version__
from .checker import Diagnostic, check_source
from .editor import EditError, EditResult, fmt, move, replace_body, wrap

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "build",
    "dist",
    "node_modules",
    ".eggs",
}


def _expand(paths: Iterable[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for candidate in sorted(path.rglob("*.py")):
                if any(part in EXCLUDED_DIRS for part in candidate.parts):
                    continue
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield candidate
        elif path.is_file():
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield path
        else:
            raise SystemExit(f"pyforai: no such file or directory: {raw}")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    except SyntaxError as exc:
        raise SystemExit(f"pyforai: {path}: cannot detect encoding: {exc}") from exc
    return raw.decode(encoding)


def _parse_anchor(value: Optional[str]) -> Optional[tuple[int, int]]:
    if value is None:
        return None
    try:
        line_text, col_text = value.split(":", 1)
        return int(line_text), int(col_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("anchor must be LINE:COL (e.g. 12:4; column is 0-based)") from exc


def _print_diagnostics(path: Path, diagnostics: list[Diagnostic]) -> None:
    for diagnostic in diagnostics:
        print(f"{path}:{diagnostic.lineno}:{diagnostic.col}: {diagnostic.code} {diagnostic.message}")
        if diagnostic.hint:
            print(f"  hint: {diagnostic.hint}")


def _print_edit_error(path: Path, operation: str, exc: EditError) -> None:
    print(f"pyforai: {path}: {operation}: {exc}", file=sys.stderr)
    for diagnostic in exc.diagnostics:
        print(
            f"  {diagnostic.code} at {diagnostic.lineno}:{diagnostic.col}: {diagnostic.message}",
            file=sys.stderr,
        )
        if diagnostic.hint:
            print(f"    hint: {diagnostic.hint}", file=sys.stderr)


def _emit_result(result: EditResult, args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return
    if result.changed:
        if result.diff:
            print(result.diff, end="")
        detail = f": {result.detail}" if result.detail else ""
        print(f"{result.path}: {result.operation}{detail}")
        if args.dry_run:
            print("(dry run: file not written)")
    else:
        print(f"{result.path}: {result.operation}: no change")


def _emit_failure(path: Path, operation: str, exc: EditError, args: argparse.Namespace) -> None:
    if args.json:
        print(
            json.dumps(
                {
                    "ok": False,
                    "path": str(path),
                    "operation": operation,
                    "error": str(exc),
                    "diagnostics": [d.as_dict() for d in exc.diagnostics],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_edit_error(path, operation, exc)


def cmd_check(args: argparse.Namespace) -> int:
    paths = list(_expand(args.paths))
    files: list[dict] = []
    errors = 0
    warnings = 0
    for path in paths:
        try:
            text = _read_text(path)
        except (OSError, UnicodeDecodeError) as exc:
            errors += 1
            files.append(
                {
                    "path": str(path),
                    "ok": False,
                    "anchors": 0,
                    "diagnostics": [
                        {
                            "code": "E000",
                            "severity": "error",
                            "line": 0,
                            "col": 0,
                            "message": str(exc),
                            "hint": "",
                        }
                    ],
                }
            )
            if not args.json:
                print(f"{path}: E000 {exc}")
            continue
        result = check_source(
            text,
            str(path),
            strict=args.strict,
            min_lines=args.min_lines,
            min_depth=args.min_depth,
        )
        errors += len(result.errors)
        warnings += len(result.warnings)
        files.append(
            {
                "path": str(path),
                "ok": result.ok,
                "anchors": len(result.matches),
                "diagnostics": [d.as_dict() for d in result.diagnostics],
            }
        )
        if not args.json and result.diagnostics:
            _print_diagnostics(path, result.diagnostics)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": errors == 0,
                    "errors": errors,
                    "warnings": warnings,
                    "files": files,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"checked {len(paths)} file(s): {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


def cmd_fmt(args: argparse.Namespace) -> int:
    paths = list(_expand(args.paths))
    results: list[dict] = []
    failed = False
    changed = 0
    for path in paths:
        try:
            result = fmt(
                path,
                min_lines=args.min_lines,
                min_depth=args.min_depth,
                all_blocks=args.all,
                dry_run=args.dry_run,
            )
        except EditError as exc:
            failed = True
            results.append(
                {
                    "ok": False,
                    "path": str(path),
                    "operation": "fmt",
                    "error": str(exc),
                    "diagnostics": [d.as_dict() for d in exc.diagnostics],
                }
            )
            if not args.json:
                _print_edit_error(path, "fmt", exc)
            continue
        if result.changed:
            changed += 1
        results.append(result.as_dict())
        if not args.json and result.changed:
            if result.diff:
                print(result.diff, end="")
            print(f"{path}: fmt: {result.detail}")
    if args.json:
        print(
            json.dumps(
                {"ok": not failed, "changed": changed, "results": results},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"fmt: {changed} file(s) changed, {len(paths)} checked")
    return 1 if failed else 0


def cmd_wrap(args: argparse.Namespace) -> int:
    handler = args.handler
    if args.handler_file:
        if args.handler_file == "-":
            handler = sys.stdin.read()
        else:
            try:
                handler = Path(args.handler_file).read_text(encoding="utf-8")
            except OSError as exc:
                _emit_failure(
                    Path(args.file),
                    "wrap",
                    EditError(f"cannot read handler file: {exc}"),
                    args,
                )
                return 1
    try:
        result = wrap(
            args.file,
            header=args.header,
            anchor=args.anchor,
            kind=args.kind,
            condition=args.condition,
            context=args.context,
            loop_target=args.target,
            iterable=args.iterable,
            except_clause=args.except_clause,
            handler=handler,
            dry_run=args.dry_run,
        )
    except EditError as exc:
        _emit_failure(Path(args.file), "wrap", exc, args)
        return 1
    _emit_result(result, args)
    return 0


def cmd_replace(args: argparse.Namespace) -> int:
    if args.code_file:
        if args.code_file == "-":
            code = sys.stdin.read()
        else:
            try:
                code = Path(args.code_file).read_text(encoding="utf-8")
            except OSError as exc:
                _emit_failure(
                    Path(args.file),
                    "replace-body",
                    EditError(f"cannot read code file: {exc}"),
                    args,
                )
                return 1
    else:
        code = args.code
    try:
        result = replace_body(
            args.file,
            header=args.header,
            anchor=args.anchor,
            code=code,
            keep_docstring=args.keep_docstring,
            dry_run=args.dry_run,
        )
    except EditError as exc:
        _emit_failure(Path(args.file), "replace-body", exc, args)
        return 1
    _emit_result(result, args)
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    try:
        result = move(
            args.file,
            header=args.header,
            anchor=args.anchor,
            before_line=args.before_line,
            after_line=args.after_line,
            into_line=args.into_line,
            dry_run=args.dry_run,
        )
    except EditError as exc:
        _emit_failure(Path(args.file), "move", exc, args)
        return 1
    _emit_result(result, args)
    return 0


def _add_target(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--header", type=int, help="1-based line of the block header")
    group.add_argument(
        "--anchor",
        type=_parse_anchor,
        help="LINE:COL of an existing anchor (column is 0-based)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyforai",
        description="Comment anchors and structural editing for AI-friendly Python.",
    )
    parser.add_argument("--version", action="version", version=f"pyforai {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate anchors (L1)")
    check.add_argument("paths", nargs="+", help="files or directories")
    check.add_argument("--strict", action="store_true", help="require anchors for large/deep blocks")
    check.add_argument("--min-lines", type=int, default=5, help="strict: minimum block span (default 5)")
    check.add_argument("--min-depth", type=int, default=3, help="strict: minimum nesting depth (default 3)")
    check.add_argument("--json", action="store_true", help="machine-readable output")
    check.set_defaults(func=cmd_check)

    fmt_parser = sub.add_parser("fmt", help="insert missing anchors (derived, not assertions)")
    fmt_parser.add_argument("paths", nargs="+", help="files or directories")
    fmt_parser.add_argument("--all", action="store_true", help="insert anchors for every multi-line block")
    fmt_parser.add_argument("--min-lines", type=int, default=5)
    fmt_parser.add_argument("--min-depth", type=int, default=3)
    fmt_parser.add_argument("--dry-run", action="store_true")
    fmt_parser.add_argument("--json", action="store_true")
    fmt_parser.set_defaults(func=cmd_fmt)

    wrap_parser = sub.add_parser("wrap", help="wrap a block in try/if/with/for/while")
    wrap_parser.add_argument("file")
    _add_target(wrap_parser)
    wrap_parser.add_argument("--kind", required=True, choices=["try", "if", "with", "for", "while"])
    wrap_parser.add_argument("--condition", help="condition for if/while")
    wrap_parser.add_argument("--context", help="context expression for with")
    wrap_parser.add_argument("--target", help="loop variable for for")
    wrap_parser.add_argument("--iterable", help="iterable expression for for")
    wrap_parser.add_argument("--except", dest="except_clause", help="text after `except `, e.g. 'Exception as e'")
    handler_group = wrap_parser.add_mutually_exclusive_group()
    handler_group.add_argument("--handler", help="except body code (default: raise)")
    handler_group.add_argument("--handler-file", help="read except body from a file ('-' for stdin)")
    wrap_parser.add_argument("--dry-run", action="store_true")
    wrap_parser.add_argument("--json", action="store_true")
    wrap_parser.set_defaults(func=cmd_wrap)

    replace_parser = sub.add_parser("replace-body", help="replace a block's body")
    replace_parser.add_argument("file")
    _add_target(replace_parser)
    code_group = replace_parser.add_mutually_exclusive_group(required=True)
    code_group.add_argument("--code", help="replacement body as a string")
    code_group.add_argument("--code-file", help="read replacement body from a file ('-' for stdin)")
    replace_parser.add_argument("--keep-docstring", action="store_true")
    replace_parser.add_argument("--dry-run", action="store_true")
    replace_parser.add_argument("--json", action="store_true")
    replace_parser.set_defaults(func=cmd_replace)

    move_parser = sub.add_parser("move", help="move a block before/after/into another block")
    move_parser.add_argument("file")
    _add_target(move_parser)
    destination_group = move_parser.add_mutually_exclusive_group(required=True)
    destination_group.add_argument("--before-line", type=int, help="insert before the statement at this line")
    destination_group.add_argument("--after-line", type=int, help="insert after the statement at this line")
    destination_group.add_argument("--into-line", type=int, help="append into the block starting at this line")
    move_parser.add_argument("--dry-run", action="store_true")
    move_parser.add_argument("--json", action="store_true")
    move_parser.set_defaults(func=cmd_move)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
