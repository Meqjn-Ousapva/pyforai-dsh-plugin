"""L2: structural edits that maintain indentation and anchors.

The editor never asks a model to perform whitespace surgery.  It resolves a
block, rewrites the relevant lines, reindents the moved/inserted body, and
refuses to write unless the result parses *and* passes the anchor checker.

Safety properties
-----------------
* The source is validated before an edit and the result is validated after it.
* Writes are atomic (temp file + ``os.replace``); a failed edit leaves the
  original untouched.
* ``dry_run`` computes the diff without writing.
* Multiline string interiors are never reindented, because their leading
  whitespace is part of the string value.
"""

from __future__ import annotations

import ast
import difflib
import io
import os
import stat
import tempfile
import textwrap
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .anchors import (
    Block,
    SourceModel,
    block_at_header,
    contains_block,
    detect_newline,
    is_blank,
    kind_of,
    leading_ws,
    string_interior_lines,
)
from .checker import CheckResult, Diagnostic, Match, check_source, plan_fmt


class EditError(Exception):
    """A structural edit could not be applied safely."""

    def __init__(self, message: str, diagnostics: Optional[list[Diagnostic]] = None):
        super().__init__(message)
        self.diagnostics = diagnostics or []


@dataclass
class EditResult:
    path: str
    operation: str
    changed: bool
    diff: str = ""
    detail: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": True,
            "path": self.path,
            "operation": self.operation,
            "changed": self.changed,
            "detail": self.detail,
            "diff": self.diff,
            "diagnostics": [d.as_dict() for d in self.diagnostics],
        }


class Document:
    """A source file split into lines, with atomic, validated writes."""

    def __init__(self, path: Path):
        self.path = path
        raw = path.read_bytes()
        try:
            self.encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        except SyntaxError as exc:
            raise EditError(f"{path}: cannot detect source encoding: {exc}") from exc
        try:
            self.text = raw.decode(self.encoding)
        except UnicodeDecodeError as exc:
            raise EditError(f"{path}: cannot decode source as {self.encoding}: {exc}") from exc
        self.original_text = self.text
        self.newline = detect_newline(self.text)
        self.final_newline = self.text.endswith(("\n", "\r"))
        self.lines = self.text.splitlines(keepends=True)
        self.tree = ast.parse(self.text, str(path))

    def render(self) -> str:
        text = "".join(self.lines)
        if not self.final_newline and text.endswith(self.newline):
            text = text[: -len(self.newline)]
        return text

    def _splice(self, start: int, end: int, new_lines: list[str]) -> None:
        """Replace ``lines[start:end]`` while keeping line endings sane."""
        if start > 0 and self.lines[start - 1] and not self.lines[start - 1].endswith(("\n", "\r")):
            self.lines[start - 1] += self.newline
        new = list(new_lines)
        if new and end < len(self.lines) and not new[-1].endswith(("\n", "\r")):
            new[-1] += self.newline
        if new and end == len(self.lines) and self.final_newline and not new[-1].endswith(("\n", "\r")):
            new[-1] += self.newline
        self.lines[start:end] = new

    def commit(self, operation: str, dry_run: bool = False, detail: str = "") -> EditResult:
        new_text = self.render()
        result = check_source(new_text, str(self.path))
        if not result.ok:
            raise EditError(
                f"refusing to write: the result has anchor errors "
                f"({result.diagnostics[0].code} at line {result.diagnostics[0].lineno})",
                result.diagnostics,
            )
        changed = new_text != self.original_text
        diff = _unified_diff(self.original_text, new_text, self.path) if changed else ""
        if changed and not dry_run:
            _atomic_write(self.path, new_text.encode(self.encoding))
        return EditResult(
            path=str(self.path),
            operation=operation,
            changed=changed,
            diff=diff,
            detail=detail,
            diagnostics=result.diagnostics,
        )


def _unified_diff(old: str, new: str, path: Path) -> str:
    try:
        shown = path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        shown = Path(str(path.resolve()).lstrip(os.sep))
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{shown}",
            tofile=f"b/{shown}",
        )
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path = path.resolve()
    fd, tmp = tempfile.mkstemp(prefix=".pyforai-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _load(path: Path) -> tuple[Document, SourceModel, CheckResult]:
    try:
        doc = Document(path)
    except SyntaxError as exc:
        raise EditError(f"{path}: syntax error at line {exc.lineno}: {exc.msg}") from exc
    except EditError:
        raise
    except OSError as exc:
        raise EditError(f"{path}: cannot read source: {exc}") from exc
    result = check_source(doc.text, str(path))
    if not result.ok or result.model is None:
        first = result.diagnostics[0] if result.diagnostics else None
        message = f"{path}: fix existing anchor errors before editing"
        if first is not None:
            message += f" ({first.code} at line {first.lineno}: {first.message})"
        raise EditError(message, result.diagnostics)
    return doc, result.model, result


def _resolve(
    model: SourceModel,
    matches: list[Match],
    header: Optional[int],
    anchor: Optional[tuple[int, int]],
) -> Block:
    if header is not None:
        block = block_at_header(model.blocks, header)
        if block is None:
            raise EditError(f"no compound statement starts at line {header}")
        return block
    if anchor is not None:
        line, col = anchor
        for match in matches:
            if match.anchor.lineno == line and match.anchor.col == col:
                return match.block
        raise EditError(
            f"no valid anchor at line {line}, column {col} (run `pyforai check`)"
        )
    raise EditError("specify header=... or anchor=...")


def _trailing_comment_end(doc: Document, block: Block, end: int) -> int:
    """Extend ``end`` over trailing comment lines indented inside the block."""
    line = end
    while line < len(doc.lines):
        text = doc.lines[line]
        if is_blank(text):
            break
        stripped = text.lstrip(" \t")
        if stripped.startswith("#") and len(text) - len(stripped) > block.col:
            line += 1
            continue
        break
    return line


def block_span(
    doc: Document,
    block: Block,
    matches: list[Match],
    *,
    include_anchor: bool = True,
) -> tuple[int, int]:
    """Return the 0-based half-open span of a block (decorators and anchor included)."""
    start = block.first_line - 1
    end = block.end_lineno
    if include_anchor:
        match = next((m for m in matches if m.block.key == block.key), None)
        if match is not None and match.anchor.lineno > end:
            return start, match.anchor.lineno
    return start, _trailing_comment_end(doc, block, end)


def indent_unit_for_block(doc: Document, block: Block) -> str:
    """Infer the indentation step used by this block's body."""
    header_prefix = leading_ws(doc.lines[block.lineno - 1])
    node = block.node
    if hasattr(ast, "Match") and isinstance(node, ast.Match):
        if node.cases:
            body_prefix = leading_ws(doc.lines[node.cases[0].pattern.lineno - 1])
            if body_prefix.startswith(header_prefix) and len(body_prefix) > len(header_prefix):
                return body_prefix[len(header_prefix) :]
        return "    "
    body = getattr(node, "body", None)
    if body:
        body_prefix = leading_ws(doc.lines[body[0].lineno - 1])
        if body_prefix.startswith(header_prefix) and len(body_prefix) > len(header_prefix):
            return body_prefix[len(header_prefix) :]
    return "    "


def _indent_lines(doc: Document, lines: list[str], start_index: int, unit: str) -> list[str]:
    skip = string_interior_lines(doc.text)
    out: list[str] = []
    for offset, line in enumerate(lines):
        line_no = start_index + offset + 1
        if is_blank(line) or line_no in skip:
            out.append(line)
        else:
            out.append(unit + line)
    return out


def _reindent_line(line: str, old_prefix: str, new_prefix: str) -> str:
    if old_prefix == new_prefix:
        return line
    if line.startswith(old_prefix):
        return new_prefix + line[len(old_prefix) :]
    return line


def _docstring_node(body: list[ast.stmt]) -> Optional[ast.stmt]:
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return body[0]
    return None


def _require(value: Optional[str], name: str) -> str:
    if value is None or not str(value).strip():
        raise EditError(f"{name} is required")
    return str(value)


def _try_wrapper(base: str, unit: str, except_clause: str, handler: str, nl: str) -> tuple[str, list[str]]:
    clause = except_clause.strip().rstrip(":")
    if not clause:
        raise EditError("except_clause must not be empty")
    header = f"{base}try:{nl}"
    trailer = [f"{base}except {clause}:{nl}"]
    handler_lines = textwrap.dedent(handler).strip("\n").splitlines() or ["pass"]
    for line in handler_lines:
        if not line.strip():
            trailer.append(nl)
        else:
            trailer.append(f"{base}{unit}{line}{nl}")
    trailer.append(f"{base}# end try{nl}")
    return header, trailer


def wrap(
    path: str | Path,
    *,
    header: Optional[int] = None,
    anchor: Optional[tuple[int, int]] = None,
    kind: str,
    condition: Optional[str] = None,
    context: Optional[str] = None,
    loop_target: Optional[str] = None,
    iterable: Optional[str] = None,
    except_clause: Optional[str] = None,
    handler: Optional[str] = None,
    dry_run: bool = False,
) -> EditResult:
    """Wrap the target block in ``kind`` (``try``/``if``/``with``/``for``/``while``)."""
    if kind not in {"try", "if", "with", "for", "while"}:
        raise EditError(f"unsupported wrapper kind: {kind!r}")
    doc, model, result = _load(Path(path))
    block = _resolve(model, result.matches, header, anchor)
    unit = indent_unit_for_block(doc, block)
    base = leading_ws(doc.lines[block.first_line - 1])
    nl = doc.newline
    start, end = block_span(doc, block, result.matches, include_anchor=True)

    if kind == "try":
        header_line, trailer = _try_wrapper(
            base, unit, except_clause or "Exception", handler if handler is not None else "raise", nl
        )
    elif kind == "if":
        header_line = f"{base}if {_require(condition, 'condition')}:{nl}"
        trailer = [f"{base}# end if{nl}"]
    elif kind == "with":
        header_line = f"{base}with {_require(context, 'context')}:{nl}"
        trailer = [f"{base}# end with{nl}"]
    elif kind == "for":
        target = _require(loop_target, "loop_target")
        values = _require(iterable, "iterable")
        header_line = f"{base}for {target} in {values}:{nl}"
        trailer = [f"{base}# end for{nl}"]
    else:  # while
        header_line = f"{base}while {_require(condition, 'condition')}:{nl}"
        trailer = [f"{base}# end while{nl}"]

    body = doc.lines[start:end]
    indented = _indent_lines(doc, body, start, unit)
    doc._splice(start, end, [header_line] + indented + trailer)
    return doc.commit("wrap", dry_run, detail=f"wrapped `{block.kind}` at line {block.lineno} in `{kind}`")


def replace_body(
    path: str | Path,
    *,
    header: Optional[int] = None,
    anchor: Optional[tuple[int, int]] = None,
    code: str,
    keep_docstring: bool = False,
    dry_run: bool = False,
) -> EditResult:
    """Replace the body of the first clause of the target block."""
    doc, model, result = _load(Path(path))
    block = _resolve(model, result.matches, header, anchor)
    if hasattr(ast, "Match") and isinstance(block.node, ast.Match):
        raise EditError("replace-body is not supported for `match`; target a case body instead")
    body = getattr(block.node, "body", None)
    if not body:
        raise EditError(f"`{block.kind}` at line {block.lineno} has no body")
    if body[0].lineno == block.lineno:
        raise EditError(
            f"cannot replace the body of a one-line `{block.kind}`; "
            "expand it to a multi-line block first"
        )

    unit = indent_unit_for_block(doc, block)
    base = leading_ws(doc.lines[block.first_line - 1])
    body_indent = base + unit
    start = body[0].lineno - 1
    end = body[-1].end_lineno

    removed_docstring = False
    docstring = _docstring_node(body)
    if docstring is not None:
        if keep_docstring:
            # Leave the existing docstring in place and start replacing after
            # it.  Re-inserting its lines here would duplicate the docstring.
            start = docstring.end_lineno
        else:
            removed_docstring = True

    code_lines = textwrap.dedent(code).strip("\n").splitlines() or ["pass"]
    new: list[str] = []
    for line in code_lines:
        if not line.strip():
            new.append(doc.newline)
        else:
            new.append(body_indent + line + doc.newline)

    doc._splice(start, end, new)
    details = [f"replaced body of `{block.kind}` at line {block.lineno}"]
    if removed_docstring and not keep_docstring:
        details.append("docstring removed")
    return doc.commit("replace-body", dry_run, detail="; ".join(details))


def _statement_at(tree: ast.AST, lineno: int) -> ast.stmt:
    candidates = [n for n in ast.walk(tree) if isinstance(n, ast.stmt) and n.lineno == lineno]
    if not candidates:
        raise EditError(f"no statement starts at line {lineno}")
    unique = {id(n): n for n in candidates}
    compounds = [n for n in unique.values() if kind_of(n) is not None]
    if compounds:
        return min(compounds, key=lambda n: (n.col_offset, n.end_lineno or n.lineno))
    if len(unique) > 1:
        raise EditError(f"line {lineno} contains multiple statements; target a compound header")
    return next(iter(unique.values()))


def _statement_span_end(doc: Document, model: SourceModel, matches: list[Match], stmt: ast.stmt) -> int:
    if kind_of(stmt) is not None:
        block = next((b for b in model.blocks if b.node is stmt), None)
        if block is not None:
            _, end = block_span(doc, block, matches, include_anchor=True)
            return end
    return stmt.end_lineno or stmt.lineno


def move(
    path: str | Path,
    *,
    header: Optional[int] = None,
    anchor: Optional[tuple[int, int]] = None,
    before_line: Optional[int] = None,
    after_line: Optional[int] = None,
    into_line: Optional[int] = None,
    dry_run: bool = False,
) -> EditResult:
    """Move a compound block before/after a statement, or into a block's body."""
    if sum(x is not None for x in (before_line, after_line, into_line)) != 1:
        raise EditError("specify exactly one of before_line, after_line, into_line")
    doc, model, result = _load(Path(path))
    block = _resolve(model, result.matches, header, anchor)
    start, end = block_span(doc, block, result.matches, include_anchor=True)
    old_prefix = leading_ws(doc.lines[start])
    moved = doc.lines[start:end]

    if into_line is not None:
        destination = block_at_header(model.blocks, into_line)
        if destination is None:
            raise EditError(f"no compound statement starts at line {into_line}")
        if hasattr(ast, "Match") and isinstance(destination.node, ast.Match):
            raise EditError("`into` is not supported for `match`; target a case body instead")
        if destination.key == block.key or contains_block(block, destination):
            raise EditError("cannot move a block into itself or one of its descendants")
        destination_body = getattr(destination.node, "body", None)
        if not destination_body:
            raise EditError(f"`{destination.kind}` at line {into_line} has no body")
        dest_pos = _statement_span_end(doc, model, result.matches, destination_body[-1])
        base = leading_ws(doc.lines[destination.first_line - 1])
        dest_indent = base + indent_unit_for_block(doc, destination)
        destination_desc = f"into block at line {into_line}"
    else:
        line = before_line if before_line is not None else after_line
        assert line is not None
        statement = _statement_at(model.tree, line)
        statement_start = statement.lineno
        if kind_of(statement) is not None:
            enclosing = next((b for b in model.blocks if b.node is statement), None)
            if enclosing is not None:
                statement_start = enclosing.first_line
        if before_line is not None:
            dest_pos = statement_start - 1
            destination_desc = f"before line {before_line}"
        else:
            dest_pos = _statement_span_end(doc, model, result.matches, statement)
            destination_desc = f"after line {after_line}"
        dest_indent = leading_ws(doc.lines[statement_start - 1])

    if start <= dest_pos <= end:
        raise EditError("destination is inside the block being moved")

    remaining = doc.lines[:start] + doc.lines[end:]
    if dest_pos > end:
        dest_pos -= end - start

    skip = string_interior_lines(doc.text)
    reindented: list[str] = []
    for offset, moved_line in enumerate(moved):
        line_no = start + offset + 1
        if line_no in skip or is_blank(moved_line):
            reindented.append(moved_line)
        else:
            reindented.append(_reindent_line(moved_line, old_prefix, dest_indent))

    remaining[dest_pos:dest_pos] = reindented
    try:
        ast.parse("".join(remaining), str(doc.path))
    except SyntaxError as exc:
        raise EditError(
            f"moving this block would break the file at line {exc.lineno}: {exc.msg}; "
            "the source block may be the only statement in its parent"
        ) from exc

    doc.lines = remaining
    return doc.commit("move", dry_run, detail=f"moved `{block.kind}` from line {block.lineno} {destination_desc}")


def fmt(
    path: str | Path,
    *,
    min_lines: int = 5,
    min_depth: int = 3,
    all_blocks: bool = False,
    dry_run: bool = False,
) -> EditResult:
    """Insert anchors for blocks that lack them (derived, not assertions)."""
    doc, model, result = _load(Path(path))
    plan = plan_fmt(
        model,
        result.matches,
        min_lines=min_lines,
        min_depth=min_depth,
        all_blocks=all_blocks,
    )
    if not plan:
        return EditResult(str(path), "fmt", False)
    # Higher lines first so earlier insertions do not shift later ones.  For a
    # shared insertion line, smaller columns are inserted first; because each
    # insertion goes to the same index, the larger column ends up above it,
    # which is the correct inner-before-outer order.
    for insertion in sorted(plan, key=lambda i: (-i.after_line, i.col)):
        anchor_line = f"{insertion.prefix}# end {insertion.kind}{doc.newline}"
        doc._splice(insertion.after_line, insertion.after_line, [anchor_line])
    return doc.commit("fmt", dry_run, detail=f"inserted {len(plan)} anchor(s)")
