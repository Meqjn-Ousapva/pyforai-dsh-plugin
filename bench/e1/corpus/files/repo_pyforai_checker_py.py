"""L1: validate anchor assertions against Python's own parse tree.

The checker treats ``# end <kind>`` as a claim about the structure of the
program.  The claim is checked against the AST; disagreement is a hard error.
That is what turns a silent "dedent to a legal-but-wrong level" into a loud,
locatable diagnostic.

Design notes
------------
* Anchors are **optional**.  The checker never complains about a missing
  anchor unless ``strict=True``.
* Anchors are **assertions, not decoration**.  Consequently :func:`check_source`
  never rewrites them; ``fmt`` only *inserts missing* anchors and refuses to
  touch a file whose existing anchors are already inconsistent.
* An anchor is a second sample of the author's structural intent.  It is not an
  independent checksum: if the author's intent and its indentation are wrong in
  the same way, the anchor will be wrong in the same way too.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable, Optional

from .anchors import (
    Anchor,
    Block,
    SourceModel,
    build_model,
    contains_block,
    kind_of,
    leading_ws,
)


@dataclass
class Diagnostic:
    """A single, machine-readable problem."""

    code: str
    message: str
    lineno: int = 0
    col: int = 0
    hint: str = ""
    severity: str = "error"

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "line": self.lineno,
            "col": self.col,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass
class Match:
    """A validated anchor-to-block binding."""

    anchor: Anchor
    block: Block


@dataclass
class CheckResult:
    ok: bool
    diagnostics: list[Diagnostic]
    matches: list[Match]
    model: Optional[SourceModel] = None

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]


@dataclass(frozen=True)
class Insertion:
    """A planned ``# end <kind>`` insertion used by ``fmt``."""

    after_line: int
    col: int
    kind: str
    prefix: str


def check_source(
    src: str,
    filename: str = "<string>",
    *,
    strict: bool = False,
    min_lines: int = 5,
    min_depth: int = 3,
) -> CheckResult:
    """Validate every anchor in ``src``.

    Parameters
    ----------
    strict:
        Also require anchors for blocks that span at least ``min_lines`` lines
        or are nested at least ``min_depth`` compound statements deep.
    """
    try:
        model = build_model(src, filename)
    except SyntaxError as exc:
        diagnostic = Diagnostic(
            code="E100",
            message=f"syntax error: {exc.msg}",
            lineno=exc.lineno or 0,
            col=max((exc.offset or 1) - 1, 0),
            hint="fix the syntax error before checking anchors",
        )
        return CheckResult(False, [diagnostic], [])

    diagnostics, matches = _match(model)
    if strict:
        diagnostics.extend(_missing_anchors(model, matches, min_lines, min_depth))
    ok = not any(d.severity == "error" for d in diagnostics)
    return CheckResult(ok, diagnostics, matches, model)


def _match(model: SourceModel) -> tuple[list[Diagnostic], list[Match]]:
    diagnostics: list[Diagnostic] = []
    matches: list[Match] = []
    consumed: set[tuple[str, int, int, int]] = set()

    for anchor in model.anchors:
        line_text = model.lines[anchor.lineno - 1] if 0 < anchor.lineno <= len(model.lines) else ""
        if line_text[: anchor.col].strip():
            diagnostics.append(
                Diagnostic(
                    "E007",
                    "anchor must be on its own line (code appears before the comment)",
                    anchor.lineno,
                    anchor.col,
                    hint="move `# end ...` to its own line at the block header's indentation",
                )
            )
            continue

        # The candidate is the most recent sibling header at this column.
        # Using "most recent header" rather than "most recent block that has
        # already ended" matters: if that header is still open, the anchor is
        # inside it, and that is a more useful diagnostic than falling back to
        # an older sibling and reporting a non-adjacent anchor.
        before = [b for b in model.blocks if b.col == anchor.col and b.lineno < anchor.lineno]
        if not before:
            diagnostics.append(
                Diagnostic(
                    "E002",
                    f"no compound statement header at column {anchor.col}",
                    anchor.lineno,
                    anchor.col,
                    hint="align the anchor with the header of the block it closes",
                )
            )
            continue

        candidate = max(before, key=lambda b: b.lineno)
        if candidate.end_lineno >= anchor.lineno:
            extra = ""
            if isinstance(candidate.node, ast.If) and getattr(candidate.node, "orelse", None):
                extra = " (it continues into an `else`/`elif` clause)"
            elif isinstance(candidate.node, ast.Try):
                extra = " (it continues into an `except`/`else`/`finally` clause)"
            diagnostics.append(
                Diagnostic(
                    "E003",
                    f"the `{candidate.kind}` at line {candidate.lineno} ends at line "
                    f"{candidate.end_lineno}{extra}; the anchor is inside it",
                    anchor.lineno,
                    anchor.col,
                    hint=f"move the anchor after line {candidate.end_lineno}",
                )
            )
            continue

        between = [s for s in model.starts if candidate.end_lineno < s[0] < anchor.lineno]
        if between:
            diagnostics.append(
                Diagnostic(
                    "E004",
                    f"code at line {between[0][0]} sits between the end of the "
                    f"`{candidate.kind}` (line {candidate.end_lineno}) and the anchor",
                    anchor.lineno,
                    anchor.col,
                    hint=f"move the anchor directly after line {candidate.end_lineno}, "
                    "or move it after the enclosing block",
                )
            )
            continue

        if candidate.kind != anchor.kind:
            earlier = [
                b
                for b in model.blocks
                if b.col == anchor.col
                and b.kind == anchor.kind
                and b.end_lineno < candidate.lineno
            ]
            hint = (
                f"the block ending here is `{candidate.kind}` (opened at line "
                f"{candidate.lineno}); write `# end {candidate.kind}`"
            )
            if earlier:
                previous = max(earlier, key=lambda b: b.end_lineno)
                hint += (
                    f", or move the anchor above the `{candidate.kind}` "
                    f"(the `{anchor.kind}` ended at line {previous.end_lineno})"
                )
            diagnostics.append(
                Diagnostic(
                    "E001",
                    f"kind mismatch: the block at column {anchor.col} is "
                    f"`{candidate.kind}` (line {candidate.lineno}), not `{anchor.kind}`",
                    anchor.lineno,
                    anchor.col,
                    hint,
                )
            )
            continue

        if candidate.key in consumed:
            diagnostics.append(
                Diagnostic(
                    "E005",
                    f"duplicate anchor: the `{candidate.kind}` at line "
                    f"{candidate.lineno} is already closed",
                    anchor.lineno,
                    anchor.col,
                    hint="remove one of the anchors",
                )
            )
            continue

        following = next((s for s in model.starts if s[0] > anchor.lineno), None)
        if following is not None and following[1] > anchor.col:
            diagnostics.append(
                Diagnostic(
                    "E006",
                    f"the first code after the anchor is at column {following[1]} "
                    f"(line {following[0]}), deeper than the anchor (column {anchor.col})",
                    anchor.lineno,
                    anchor.col,
                    hint="the block does not end here; move the anchor after the block",
                )
            )
            continue

        consumed.add(candidate.key)
        matches.append(Match(anchor, candidate))

    # Anchors close blocks; if an inner block has an anchor it must be closed
    # before the enclosing block's anchor.
    reported: set[tuple[int, int]] = set()
    for outer in matches:
        for inner in matches:
            if outer is inner:
                continue
            if contains_block(outer.block, inner.block) and outer.anchor.lineno < inner.anchor.lineno:
                key = (outer.anchor.lineno, outer.anchor.col)
                if key in reported:
                    continue
                reported.add(key)
                diagnostics.append(
                    Diagnostic(
                        "E008",
                        f"the anchor for the outer `{outer.block.kind}` (line "
                        f"{outer.anchor.lineno}) appears before the anchor for the "
                        f"inner `{inner.block.kind}` (line {inner.anchor.lineno})",
                        outer.anchor.lineno,
                        outer.anchor.col,
                        hint=f"move `# end {outer.block.kind}` after line {inner.anchor.lineno}",
                    )
                )

    return diagnostics, matches


def _block_depths(tree: ast.AST) -> dict[tuple[int, int], int]:
    """Map ``(lineno, col)`` of each compound header to its nesting depth."""
    depths: dict[tuple[int, int], int] = {}

    def visit(node: ast.AST, depth: int) -> None:
        if kind_of(node) is not None:
            depths[(node.lineno, node.col_offset)] = depth
            depth += 1
        for child in ast.iter_child_nodes(node):
            visit(child, depth)

    visit(tree, 0)
    return depths


def _missing_anchors(
    model: SourceModel,
    matches: Iterable[Match],
    min_lines: int,
    min_depth: int,
) -> list[Diagnostic]:
    matched = {m.block.key for m in matches}
    depths = _block_depths(model.tree)
    diagnostics: list[Diagnostic] = []
    for block in model.blocks:
        if block.is_one_line or block.key in matched:
            continue
        depth = depths.get((block.lineno, block.col), 0)
        span = block.end_lineno - block.lineno + 1
        if span >= min_lines or depth >= min_depth:
            diagnostics.append(
                Diagnostic(
                    "E010",
                    f"missing anchor for `{block.kind}` at line {block.lineno} "
                    f"(block spans {span} lines, depth {depth})",
                    block.lineno,
                    block.col,
                    hint=f"add `# end {block.kind}` after line {block.end_lineno} "
                    "(or run `pyforai fmt`)",
                )
            )
    return diagnostics


def plan_fmt(
    model: SourceModel,
    matches: Iterable[Match],
    *,
    min_lines: int = 5,
    min_depth: int = 3,
    all_blocks: bool = False,
) -> list[Insertion]:
    """Plan anchors to insert for blocks that currently have none.

    ``fmt`` inserts *derived* anchors: they mirror the AST, so they improve
    readability and give editors a handle, but they add no validation value.
    Real validation comes from anchors written before the code is trusted.
    """
    matched = {m.block.key for m in matches}
    depths = _block_depths(model.tree)
    plan: list[Insertion] = []
    for block in model.blocks:
        if block.is_one_line or block.key in matched:
            continue
        depth = depths.get((block.lineno, block.col), 0)
        span = block.end_lineno - block.lineno + 1
        if not all_blocks and span < min_lines and depth < min_depth:
            continue
        plan.append(
            Insertion(
                after_line=_anchor_insertion_line(model, block),
                col=block.col,
                kind=block.kind,
                prefix=leading_ws(model.lines[block.lineno - 1]),
            )
        )
    return plan


def _anchor_insertion_line(model: SourceModel, block: Block) -> int:
    """Return the 1-based line after which the block's anchor should be inserted.

    Consecutive comment-only lines that are indented deeper than the block
    header are treated as trailing comments and kept *inside* the block; the
    anchor goes after them.
    """
    line = block.end_lineno
    while line < len(model.lines):
        text = model.lines[line]  # 0-based index == line number of the next line
        if not text.strip(" \t\r\n"):
            break
        stripped = text.lstrip(" \t")
        if stripped.startswith("#") and len(text) - len(stripped) > block.col:
            line += 1
            continue
        break
    return line
