"""Inject syntax-valid structural drift into real Python files.

The injector is the deterministic half of E1.  For a chosen compound block it

1. inserts one ``# end <kind>`` anchor (the frozen "assertion"), then
2. changes either the anchor or the code so the anchor and the AST disagree,
   while the file still parses.

Every case records the diagnostic codes the checker is expected to produce.
The suite in :mod:`bench.e1.run_drift` compares that expectation with reality,
so a change in the checker's diagnostics is visible.

Drift classes are split by what moved:

* ``anchor``: the anchor was edited/moved (E001/E002/E003/E005/E007/E008).
* ``code``:   the code was re-indented/moved and the anchor stayed put
              (E003/E004).
* ``coverage``: the anchor was deleted; only ``--strict`` can notice (E010).
* ``limitation``: the anchor was moved together with the code, so the checker
              cannot notice.  These are reported separately, never counted as
              a detection success.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Callable, Optional

from .common import KINDS, build_model, check_source, compile_ok

NEWLINE = "\n"


class InjectionError(ValueError):
    """The requested drift could not be produced on this block."""


@dataclass(frozen=True)
class Target:
    file_id: str
    index: int
    kind: str
    lineno: int
    end_lineno: int
    col: int
    span: int

    @property
    def key(self) -> str:
        return f"{self.file_id}:{self.index}:{self.kind}:{self.lineno}-{self.end_lineno}:{self.col}"


@dataclass
class DriftCase:
    case_id: str
    file_id: str
    drift: str
    target: Target
    expected_codes: tuple[str, ...]
    expect_detect: bool
    expect_strict: bool
    source: str
    clean_source: str
    anchor_line: int
    drift_line: int
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "file_id": self.file_id,
            "drift": self.drift,
            "target": {
                "kind": self.target.kind,
                "lineno": self.target.lineno,
                "end_lineno": self.target.end_lineno,
                "col": self.target.col,
                "span": self.target.span,
            },
            "expected_codes": list(self.expected_codes),
            "expect_detect": self.expect_detect,
            "expect_strict": self.expect_strict,
            "anchor_line": self.anchor_line,
            "drift_line": self.drift_line,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# block selection


def enumerate_targets(text: str, file_id: str, *, min_span: int = 4, per_file: int = 3) -> list[Target]:
    """Pick a small, size-diverse set of blocks from one file.

    A single anchor is inserted per case, so files with hundreds of blocks would
    otherwise dominate the corpus.  Sampling by span quartiles gives small,
    medium, and large blocks from every file.
    """
    model = build_model(text)
    candidates: list[Target] = []
    for index, block in enumerate(model.blocks):
        if block.is_one_line:
            continue
        span = block.end_lineno - block.lineno + 1
        if span < min_span:
            continue
        if block.kind not in KINDS:
            continue
        # A block whose header is a decorator's target is fine; the anchor goes
        # after the whole statement, and first_line is used by the editor.
        candidates.append(
            Target(
                file_id=file_id,
                index=index,
                kind=block.kind,
                lineno=block.lineno,
                end_lineno=block.end_lineno,
                col=block.col,
                span=span,
            )
        )
    if not candidates:
        return []
    candidates.sort(key=lambda t: (t.span, t.lineno))
    if len(candidates) <= per_file:
        return candidates
    picks: list[Target] = []
    for fraction in (0.2, 0.5, 0.8):
        idx = min(len(candidates) - 1, int(len(candidates) * fraction))
        target = candidates[idx]
        if target not in picks:
            picks.append(target)
    # Fill up to per_file with the largest remaining blocks.
    for target in sorted(candidates, key=lambda t: (-t.span, t.lineno)):
        if len(picks) >= per_file:
            break
        if target not in picks:
            picks.append(target)
    return picks[:per_file]


def code_drift_targets(
    text: str, file_id: str, *, min_span: int = 4, per_file: int = 6, min_body: int = 2
) -> list[Target]:
    """Targets that can lose their last statement without emptying the block."""
    model = build_model(text)
    candidates: list[Target] = []
    for index, block in enumerate(model.blocks):
        if block.is_one_line:
            continue
        span = block.end_lineno - block.lineno + 1
        if span < min_span or block.kind not in KINDS:
            continue
        if _has_clauses(block):
            continue
        body = getattr(block.node, "body", None)
        if not isinstance(body, list) or len(body) < min_body:
            continue
        last = body[-1]
        if isinstance(
            last,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncWith,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Match,
            ),
        ):
            continue
        if last.col_offset <= block.col:
            continue
        if last.end_lineno - last.lineno > 8:
            continue
        candidates.append(
            Target(
                file_id=file_id,
                index=index,
                kind=block.kind,
                lineno=block.lineno,
                end_lineno=block.end_lineno,
                col=block.col,
                span=span,
            )
        )
    candidates.sort(key=lambda t: (t.span, t.lineno))
    return candidates[:per_file]


def hoist_targets(text: str, file_id: str, *, per_file: int = 8) -> list[Target]:
    """Blocks whose last statement can be hoisted out, including one-liners."""
    model = build_model(text)
    candidates: list[Target] = []
    for index, block in enumerate(model.blocks):
        if block.kind not in KINDS:
            continue
        if _has_clauses(block):
            continue
        body = getattr(block.node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        last = body[-1]
        if isinstance(
            last,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncWith,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Match,
            ),
        ):
            continue
        if last.col_offset <= block.col:
            continue
        if last.end_lineno - last.lineno > 8:
            continue
        candidates.append(
            Target(
                file_id=file_id,
                index=index,
                kind=block.kind,
                lineno=block.lineno,
                end_lineno=block.end_lineno,
                col=block.col,
                span=block.end_lineno - block.lineno + 1,
            )
        )
    candidates.sort(key=lambda t: (t.span, t.lineno))
    return candidates[:per_file]


def else_drift_targets(text: str, file_id: str, *, per_file: int = 8) -> list[Target]:
    """``if`` blocks with a simple final ``else`` body that can be hoisted."""
    model = build_model(text)
    candidates: list[Target] = []
    for index, block in enumerate(model.blocks):
        node = block.node
        if not isinstance(node, ast.If):
            continue
        orelse = getattr(node, "orelse", None)
        if not orelse:
            continue
        if isinstance(orelse[0], ast.If):
            # ``elif`` chain; use the final else of the chain instead.
            continue
        last = orelse[-1]
        if isinstance(
            last,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncWith,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Match,
            ),
        ):
            continue
        if last.col_offset <= block.col:
            continue
        if last.end_lineno - last.lineno > 8:
            continue
        candidates.append(
            Target(
                file_id=file_id,
                index=index,
                kind=block.kind,
                lineno=block.lineno,
                end_lineno=block.end_lineno,
                col=block.col,
                span=block.end_lineno - block.lineno + 1,
            )
        )
    candidates.sort(key=lambda t: (t.span, t.lineno))
    return candidates[:per_file]


# ---------------------------------------------------------------------------
# source editing helpers


def _split(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _join(lines: list[str]) -> str:
    return "".join(lines)


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _prefix(text: str, line: int, col: int) -> str:
    lines = _split(text)
    if not (1 <= line <= len(lines)):
        raise InjectionError(f"line {line} out of range")
    raw = lines[line - 1]
    return raw[:col]


def _insert_anchor(text: str, target: Target) -> tuple[str, int]:
    """Insert ``# end <kind>`` after the target block; return (text, 1-based line)."""
    lines = _split(text)
    end = target.end_lineno
    if not (1 <= end <= len(lines)):
        raise InjectionError(f"target end line {end} out of range")
    if not lines[end - 1].endswith(("\n", "\r")):
        lines[end - 1] += _newline(text)
    prefix = lines[target.lineno - 1][: target.col]
    anchor = f"{prefix}# end {target.kind}{_newline(text)}"
    lines.insert(end, anchor)
    new_text = _join(lines)
    try:
        ast.parse(new_text)
    except SyntaxError as exc:
        raise InjectionError(f"anchor insertion broke syntax: {exc}") from exc
    result = check_source(new_text)
    if not result.ok:
        codes = [d.code for d in result.errors]
        raise InjectionError(f"anchor insertion is not clean: {codes}")
    return new_text, end + 1


def _replace_line(text: str, line: int, value: str) -> str:
    lines = _split(text)
    if not (1 <= line <= len(lines)):
        raise InjectionError(f"line {line} out of range")
    if not value.endswith(("\n", "\r")):
        value += _newline(text)
    lines[line - 1] = value
    return _join(lines)


def _insert_line(text: str, index: int, value: str) -> str:
    """Insert before 1-based ``index``."""
    lines = _split(text)
    if not (1 <= index <= len(lines) + 1):
        raise InjectionError(f"index {index} out of range")
    if not value.endswith(("\n", "\r")):
        value += _newline(text)
    lines.insert(index - 1, value)
    return _join(lines)


def _delete_line(text: str, line: int) -> str:
    lines = _split(text)
    if not (1 <= line <= len(lines)):
        raise InjectionError(f"line {line} out of range")
    del lines[line - 1]
    return _join(lines)


def _expect(text: str, codes: tuple[str, ...], *, strict: bool = False) -> None:
    result = check_source(text, strict=strict)
    actual = tuple(diagnostic_codes(result))
    if codes and not any(code in actual for code in codes):
        raise InjectionError(f"expected {codes}, got {actual}")
    if not codes and actual:
        raise InjectionError(f"expected no diagnostics, got {actual}")


def diagnostic_codes(result) -> list[str]:
    return sorted({d.code for d in result.diagnostics})


def _block_body_last(block) -> Optional[ast.stmt]:
    node = block.node
    body = getattr(node, "body", None)
    if not isinstance(body, list) or not body:
        return None
    return body[-1]


def _has_clauses(block) -> bool:
    node = block.node
    if isinstance(node, ast.If):
        return bool(node.orelse)
    if isinstance(node, ast.Try):
        return bool(node.handlers or node.orelse or node.finalbody)
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        return bool(node.orelse)
    return False


def _indent_width(text: str, target: Target) -> int:
    lines = _split(text)
    if target.end_lineno <= target.lineno:
        raise InjectionError("empty block")
    body_line = lines[target.lineno - 1 + 1] if target.lineno < len(lines) else ""
    body_prefix = body_line[: len(body_line) - len(body_line.lstrip(" \t"))]
    header_prefix = lines[target.lineno - 1][: target.col]
    delta = len(body_prefix) - len(header_prefix)
    if delta <= 0:
        raise InjectionError("could not determine body indentation")
    return delta


def _dedent_line(line: str, width: int) -> str:
    if line.startswith(" " * width):
        return line[width:]
    if line.startswith("\t"):
        return line[1:]
    raise InjectionError("line is not indented as expected")


# ---------------------------------------------------------------------------
# individual drift classes


def _drift_kind_mismatch(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    lines = _split(text)
    original = lines[anchor_line - 1]
    prefix = original[: len(original) - len(original.lstrip(" \t"))]
    fallback = None
    for kind in KINDS:
        if kind == target.kind:
            continue
        candidate = _replace_line(text, anchor_line, f"{prefix}# end {kind}")
        fallback = candidate
        try:
            _expect(candidate, ("E001",))
        except InjectionError:
            continue
        return candidate, anchor_line, {"changed": "anchor-kind", "new_kind": kind}
    if fallback is not None:
        return fallback, anchor_line, {"changed": "anchor-kind", "new_kind": "?"}
    raise InjectionError("no kind mismatch candidate")


def _drift_wrong_column(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    fallback = None
    for extra in (2, 3, 1, 4):
        candidate = _replace_line(
            text, anchor_line, " " * extra + _split(text)[anchor_line - 1]
        )
        fallback = candidate
        try:
            _expect(candidate, ("E002",))
        except InjectionError:
            continue
        return candidate, anchor_line, {"changed": "anchor-column", "extra_spaces": extra}
    if fallback is not None:
        return fallback, anchor_line, {"changed": "anchor-column", "extra_spaces": 0}
    raise InjectionError("no column shift candidate")


def _drift_inside_block(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    # Move the anchor just before the block's last line.  It is then inside the
    # block, which is E003.
    lines = _split(text)
    anchor = lines[anchor_line - 1]
    move_to = target.end_lineno
    candidate = _delete_line(text, anchor_line)
    candidate = _insert_line(candidate, move_to, anchor)
    return candidate, move_to, {"changed": "anchor-moved-inside"}


def _drift_not_adjacent(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    prefix = _prefix(text, target.lineno, target.col)
    candidate = _insert_line(text, anchor_line, f"{prefix}pass")
    return candidate, anchor_line, {"changed": "code-between"}


def _drift_duplicate(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    lines = _split(text)
    anchor = lines[anchor_line - 1]
    candidate = _insert_line(text, anchor_line, anchor)
    return candidate, anchor_line, {"changed": "anchor-duplicated"}


def _drift_trailing_code(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    lines = _split(text)
    original = lines[anchor_line - 1]
    prefix = original[: len(original) - len(original.lstrip(" \t"))]
    candidate = _replace_line(text, anchor_line, f"{prefix}pass  # end {target.kind}")
    return candidate, anchor_line, {"changed": "code-before-anchor"}


def _drift_dedent_last(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    if _has_clauses_from_text(text, target):
        raise InjectionError("block has clauses; dedent would be ambiguous")
    lines = _split(text)
    last = _last_simple_statement(text, target)
    if last is None:
        raise InjectionError("no simple last statement")
    width = last.col_offset - target.col
    if width <= 0:
        raise InjectionError("could not determine body indentation")
    line_no = last.lineno
    candidate = text
    for offset in range(last.end_lineno - last.lineno + 1):
        line = _split(candidate)[line_no - 1 + offset]
        candidate = _replace_line(candidate, line_no + offset, _dedent_line(line, width))
    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        raise InjectionError(f"dedent broke syntax: {exc}") from exc
    return candidate, line_no, {"changed": "code-dedented"}


def _drift_hoist_last(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    """Move the last statement out of a block, replacing an emptied body with pass.

    Unlike ``dedent_last`` this also works for one-statement bodies.  The
    hoisted line sits between the block's new end and the anchor, so the
    checker reports E004.  The code still parses unless the statement is
    illegal at the parent level (``return`` at module level, ``break`` outside a
    loop), in which case the caller skips the target.
    """
    if _has_clauses_from_text(text, target):
        raise InjectionError("block has clauses; hoist would be ambiguous")
    lines = _split(text)
    model = build_model(text)
    block = model.blocks[target.index]
    body = getattr(block.node, "body", None)
    if not isinstance(body, list) or not body:
        raise InjectionError("empty block")
    last = body[-1]
    if isinstance(
        last,
        (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.Try,
            ast.With,
            ast.AsyncWith,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Match,
        ),
    ):
        raise InjectionError("last statement is compound")
    width = last.col_offset - target.col
    if width <= 0:
        raise InjectionError("could not determine body indentation")
    if len(body) == 1:
        body_prefix = lines[last.lineno - 1][: last.col_offset]
        candidate = _insert_line(text, last.lineno, f"{body_prefix}pass")
        last_line = last.lineno + 1
    else:
        candidate = text
        last_line = last.lineno
    for offset in range(last.end_lineno - last.lineno + 1):
        line = _split(candidate)[last_line - 1 + offset]
        candidate = _replace_line(candidate, last_line + offset, _dedent_line(line, width))
    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        raise InjectionError(f"hoist broke syntax: {exc}") from exc
    return candidate, last_line, {"changed": "code-hoisted"}


def _drift_hoist_oneline(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    """Hoist the body of a one-line block (``if cond: stmt``) out of it.

    The block becomes ``if cond: pass`` and the original statement is inserted
    at the parent indentation, before the anchor.  The checker reports E004.
    """
    model = build_model(text)
    block = model.blocks[target.index]
    if not block.is_one_line:
        raise InjectionError("not a one-line block")
    body = getattr(block.node, "body", None)
    if not isinstance(body, list) or not body:
        raise InjectionError("empty block")
    last = body[-1]
    if last.lineno != block.lineno or last.end_lineno != block.lineno:
        raise InjectionError("body is not on the header line")
    lines = _split(text)
    line = lines[block.lineno - 1]
    header = line[: last.col_offset]
    if ";" in header or not header.rstrip().endswith(":"):
        raise InjectionError("one-line body is not a simple header")
    statement = line[last.col_offset :].strip()
    if not statement:
        raise InjectionError("empty one-line body")
    newline = _newline(text)
    header_line = header.rstrip() + " pass" + newline
    hoisted = " " * block.col + statement + newline
    candidate = _replace_line(text, block.lineno, header_line)
    candidate = _insert_line(candidate, block.lineno + 1, hoisted)
    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        raise InjectionError(f"one-line hoist broke syntax: {exc}") from exc
    return candidate, block.lineno + 1, {"changed": "one-line-hoist"}


def _drift_hoist_else(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    """Hoist the last statement of an ``else`` body out of the ``if``.

    This is the silent-drift shape: the public examples often still pass, but a
    hidden branch now executes one extra statement.  The checker reports E004
    because the hoisted line sits between the block end and the anchor.
    """
    model = build_model(text)
    block = model.blocks[target.index]
    node = block.node
    orelse = getattr(node, "orelse", None)
    if not isinstance(node, ast.If) or not orelse:
        raise InjectionError("not an if/else block")
    if isinstance(orelse[0], ast.If):
        raise InjectionError("elif chain is not a simple else")
    last = orelse[-1]
    width = last.col_offset - target.col
    if width <= 0:
        raise InjectionError("could not determine else indentation")
    lines = _split(text)
    if len(orelse) == 1:
        body_prefix = lines[last.lineno - 1][: last.col_offset]
        candidate = _insert_line(text, last.lineno, f"{body_prefix}pass")
        last_line = last.lineno + 1
    else:
        candidate = text
        last_line = last.lineno
    for offset in range(last.end_lineno - last.lineno + 1):
        line = _split(candidate)[last_line - 1 + offset]
        candidate = _replace_line(candidate, last_line + offset, _dedent_line(line, width))
    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        raise InjectionError(f"else hoist broke syntax: {exc}") from exc
    return candidate, last_line, {"changed": "else-hoist"}


def _drift_missing_anchor(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    candidate = _delete_line(text, anchor_line)
    return candidate, anchor_line, {"changed": "anchor-deleted"}


def _drift_consistent_shift(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    """Move the last body line out and move the anchor with it.

    This is the checker's known blind spot: if the anchor moves consistently
    with the code, there is nothing to disagree with.
    """
    if _has_clauses_from_text(text, target):
        raise InjectionError("block has clauses; consistent shift is ambiguous")
    lines = _split(text)
    last = _last_simple_statement(text, target)
    if last is None or last.end_lineno != last.lineno:
        raise InjectionError("no simple last statement")
    width = last.col_offset - target.col
    if width <= 0:
        raise InjectionError("could not determine body indentation")
    line_no = last.lineno
    anchor = lines[anchor_line - 1]
    candidate = _delete_line(text, anchor_line)
    # Dedent the whole last statement, then put the anchor before it.
    for offset in range(last.end_lineno - last.lineno + 1):
        line = _split(candidate)[line_no - 1 + offset]
        candidate = _replace_line(candidate, line_no + offset, _dedent_line(line, width))
    candidate = _insert_line(candidate, line_no, anchor)
    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        raise InjectionError(f"consistent shift broke syntax: {exc}") from exc
    return candidate, line_no, {"changed": "anchor-moved-with-code"}


def _last_simple_statement(text: str, target: Target) -> Optional[ast.stmt]:
    model = build_model(text)
    block = model.blocks[target.index]
    last = _block_body_last(block)
    if last is None:
        return None
    if isinstance(
        last,
        (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.Try,
            ast.With,
            ast.AsyncWith,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Match,
        ),
    ):
        return None
    return last


def _has_clauses_from_text(text: str, target: Target) -> bool:
    model = build_model(text)
    return _has_clauses(model.blocks[target.index])


def _drift_nested_outer_first(text: str, target: Target, anchor_line: int) -> tuple[str, int, dict]:
    """Move an inner anchor below the outer block, with the outer anchor first.

    This is the E008 shape: both anchors are after the outer block, but the
    outer one appears before the inner one.  The inner anchor is indented to
    its own header column, so the checker can bind it to the inner block.
    """
    model = build_model(text)
    outer = model.blocks[target.index]
    inner = None
    for block in model.blocks:
        # The inner block must be the last statement of the outer block;
        # otherwise there is code between the inner end and the anchor, which
        # produces E004 instead of E008.
        if block.lineno > outer.lineno and block.end_lineno == outer.end_lineno:
            inner = block
            break
    if inner is None:
        raise InjectionError("no nested last statement")
    # Drop the existing outer anchor, then insert both anchors after the outer
    # block.  Insert the inner one first; the outer insertion at the same index
    # ends up above it.
    clean = _delete_line(text, anchor_line)
    nl = _newline(clean)
    lines = _split(clean)
    end = outer.end_lineno
    if not lines[end - 1].endswith(("\n", "\r")):
        lines[end - 1] += nl
    outer_prefix = " " * outer.col
    inner_prefix = " " * inner.col
    lines.insert(end, f"{inner_prefix}# end {inner.kind}{nl}")
    lines.insert(end, f"{outer_prefix}# end {outer.kind}{nl}")
    candidate = _join(lines)
    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        raise InjectionError(f"nested swap broke syntax: {exc}") from exc
    return candidate, end + 1, {
        "changed": "anchor-order",
        "inner_anchor": end + 2,
        "inner_kind": inner.kind,
    }


EXPECTED_CODES: dict[str, tuple[str, ...]] = {
    "kind_mismatch": ("E001",),
    "wrong_column": ("E002",),
    "inside_block": ("E003",),
    "not_adjacent": ("E004",),
    "duplicate": ("E005",),
    "trailing_code": ("E007",),
    "outer_before_inner": ("E008",),
    "dedent_last": ("E004",),
    "hoist_last": ("E004",),
    "hoist_oneline": ("E004",),
    "hoist_else": ("E004",),
    "missing_anchor": (),
    "consistent_shift": (),
}

DRIFTS: dict[str, tuple[str, bool, bool, Callable]] = {
    # name: (source_kind, expect_detect, expect_strict, fn)
    "kind_mismatch": ("anchor", True, True, _drift_kind_mismatch),
    "wrong_column": ("anchor", True, True, _drift_wrong_column),
    "inside_block": ("anchor", True, True, _drift_inside_block),
    "not_adjacent": ("code", True, True, _drift_not_adjacent),
    "duplicate": ("anchor", True, True, _drift_duplicate),
    "trailing_code": ("anchor", True, True, _drift_trailing_code),
    "outer_before_inner": ("anchor", True, True, _drift_nested_outer_first),
    "dedent_last": ("code", True, True, _drift_dedent_last),
    "hoist_last": ("code", True, True, _drift_hoist_last),
    "hoist_oneline": ("code", True, True, _drift_hoist_oneline),
    "hoist_else": ("code", True, True, _drift_hoist_else),
    "missing_anchor": ("coverage", False, True, _drift_missing_anchor),
    "consistent_shift": ("limitation", False, False, _drift_consistent_shift),
}


ERROR_CODES = {"E001", "E002", "E003", "E004", "E005", "E006", "E007", "E008"}


def _anchor_positions(text: str) -> tuple[tuple[int, int, str], ...]:
    result = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip(" \t")
        if stripped.startswith("# end "):
            result.append((lineno, len(line) - len(stripped), stripped.strip()))
    return tuple(result)


def _anchor_sig(text: str) -> tuple[tuple[int, str], ...]:
    result = []
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if stripped.startswith("# end "):
            result.append((len(line) - len(stripped), stripped.strip()))
    return tuple(result)


def make_case(
    clean_text: str,
    target: Target,
    drift: str,
    *,
    case_id: Optional[str] = None,
    require_detection: bool = False,
) -> DriftCase:
    if drift not in DRIFTS:
        raise InjectionError(f"unknown drift: {drift}")
    source_kind, expect_detect, expect_strict, fn = DRIFTS[drift]
    anchored, anchor_line = _insert_anchor(clean_text, target)
    case_clean = anchored
    candidate, drift_line, meta = fn(anchored, target, anchor_line)
    if not compile_ok(candidate):
        raise InjectionError("drift produced a syntax error")
    result = check_source(candidate)
    codes = tuple(diagnostic_codes(result))
    strict = check_source(candidate, strict=True)
    strict_codes = tuple(diagnostic_codes(strict))
    before_ast = ast.dump(ast.parse(case_clean), include_attributes=False)
    after_ast = ast.dump(ast.parse(candidate), include_attributes=False)
    before_anchor = _anchor_positions(case_clean)
    after_anchor = _anchor_positions(candidate)
    changed = before_ast != after_ast or before_anchor != after_anchor
    if not changed:
        raise InjectionError("injection did not change the AST or the anchors")
    if require_detection:
        detected = any(code in ERROR_CODES for code in codes)
        if expect_detect and not detected:
            raise InjectionError(f"drift not detected: {codes}")
        if not expect_detect and detected:
            raise InjectionError(f"limitation case unexpectedly detected: {codes}")
        if expect_strict and "E010" not in strict_codes and drift == "missing_anchor":
            raise InjectionError("strict did not report E010")
    case_id = case_id or f"{target.file_id}__{drift}__L{target.lineno}"
    return DriftCase(
        case_id=case_id,
        file_id=target.file_id,
        drift=drift,
        target=target,
        expected_codes=EXPECTED_CODES[drift],
        expect_detect=expect_detect,
        expect_strict=expect_strict,
        source=candidate,
        clean_source=anchored,
        anchor_line=anchor_line,
        drift_line=drift_line,
        meta={**meta, "source_kind": source_kind},
    )
