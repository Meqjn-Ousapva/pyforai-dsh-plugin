"""Core model for comment anchors and compound blocks.

An anchor is a comment of the form ``# end <kind>`` placed at the same
indentation as the header of the compound statement it closes::

    for item in items:
        if item.ok:
            use(item)
        # end if
    # end for

Python's parser ignores the comment.  That is the point: anchors add a second,
explicit representation of block structure without changing the grammar, so
the enormous Python training corpus stays usable.

This module contains only the syntax/model layer.  Validation lives in
:mod:`pyforai.checker` and structural editing in :mod:`pyforai.editor`.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from typing import Iterable, Optional

KINDS: tuple[str, ...] = ("if", "for", "while", "try", "with", "def", "class", "match")
KIND_SET = frozenset(KINDS)

# ``# end if`` or ``# end if  # optional note``.  Only known kinds are
# accepted, and arbitrary trailing prose is rejected, so ordinary comments such
# as ``# end of file`` are not mistaken for anchors.
_KIND_PATTERN = "|".join(KINDS)
ANCHOR_RE = re.compile(rf"^#\s*end\s+(?P<kind>{_KIND_PATTERN})\s*(?:#.*)?$")

_IGNORED_TOKENS = frozenset(
    {
        tokenize.ENCODING,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.COMMENT,
        tokenize.ENDMARKER,
    }
)

_STRING_TOKENS: set[int] = {tokenize.STRING}
for _name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    _value = getattr(tokenize, _name, None)
    if _value is not None:
        _STRING_TOKENS.add(_value)
del _name, _value


def kind_of(node: ast.AST) -> Optional[str]:
    """Return the anchor kind for a compound statement node, else ``None``."""
    if isinstance(node, ast.If):
        return "if"
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return "for"
    if isinstance(node, ast.While):
        return "while"
    if isinstance(node, ast.Try):
        return "try"
    if hasattr(ast, "TryStar") and isinstance(node, ast.TryStar):  # Python 3.11+
        return "try"
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "with"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "def"
    if isinstance(node, ast.ClassDef):
        return "class"
    if hasattr(ast, "Match") and isinstance(node, ast.Match):  # Python 3.10+
        return "match"
    return None


@dataclass(frozen=True)
class Block:
    """A compound statement, identified by its header and its last line."""

    kind: str
    lineno: int
    col: int
    end_lineno: int
    node: ast.AST = field(compare=False, repr=False)

    @property
    def key(self) -> tuple[str, int, int, int]:
        return (self.kind, self.lineno, self.col, self.end_lineno)

    @property
    def first_line(self) -> int:
        """First physical line, including decorators for def/class."""
        decorators = getattr(self.node, "decorator_list", None) or []
        if decorators:
            return min(d.lineno for d in decorators)
        return self.lineno

    @property
    def is_one_line(self) -> bool:
        return self.end_lineno <= self.lineno


@dataclass(frozen=True)
class Anchor:
    """A parsed ``# end <kind>`` comment."""

    kind: str
    lineno: int
    col: int
    text: str = ""


@dataclass
class SourceModel:
    """Everything the checker and editor need to reason about one source text."""

    src: str
    filename: str
    tree: ast.Module
    lines: list[str]
    blocks: list[Block]
    anchors: list[Anchor]
    starts: list[tuple[int, int]]
    newline: str


def build_model(src: str, filename: str = "<string>") -> SourceModel:
    """Parse ``src`` and build the anchor/block model.

    Raises :class:`SyntaxError` if the source does not parse.  A leading UTF-8
    BOM is stripped so that callers that decoded with plain ``utf-8`` (rather
    than ``utf-8-sig``) still work.
    """
    if src.startswith("\ufeff"):
        src = src[1:]
    tree = ast.parse(src, filename)
    lines = src.splitlines(keepends=True)
    blocks = collect_blocks(tree)
    # ``elif`` is an ``If`` node nested in ``orelse``; the enclosing ``if``
    # already covers the whole statement.  Keeping both would let an anchor
    # bind to the ``elif`` instead of the outer block, so drop the nested one.
    blocks = [
        block
        for block in blocks
        if not (
            isinstance(block.node, ast.If)
            and 0 < block.lineno <= len(lines)
            and lines[block.lineno - 1].lstrip(" \t").startswith("elif ")
        )
    ]
    return SourceModel(
        src=src,
        filename=filename,
        tree=tree,
        lines=lines,
        blocks=blocks,
        anchors=find_anchors(src),
        starts=logical_starts(src),
        newline=detect_newline(src),
    )


def collect_blocks(tree: ast.AST) -> list[Block]:
    """Collect every compound statement, sorted by position."""
    blocks: list[Block] = []
    for node in ast.walk(tree):
        kind = kind_of(node)
        if kind is None:
            continue
        end_lineno = getattr(node, "end_lineno", None)
        if end_lineno is None:  # pragma: no cover - parsed trees always have it
            continue
        blocks.append(Block(kind, node.lineno, node.col_offset, end_lineno, node))
    blocks.sort(key=lambda b: (b.lineno, b.col, b.end_lineno))
    return blocks


def find_anchors(src: str) -> list[Anchor]:
    """Return every well-formed anchor comment, in source order."""
    anchors: list[Anchor] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                continue
            match = ANCHOR_RE.match(tok.string)
            if match and match.group("kind") in KIND_SET:
                anchors.append(Anchor(match.group("kind"), tok.start[0], tok.start[1], tok.string))
    except (tokenize.TokenError, IndentationError):
        # The caller normally parses first; if tokenization fails the syntax
        # error is reported elsewhere.
        pass
    return anchors


def logical_starts(src: str) -> list[tuple[int, int]]:
    """Return ``(line, col)`` for the first token of every logical line.

    Continuation lines inside brackets or after a backslash are *not* logical
    line starts, which is what the anchor checker wants: it needs to know
    whether a real statement begins between two positions.
    """
    starts: list[tuple[int, int]] = []
    at_start = True
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.ENCODING, tokenize.NL, tokenize.COMMENT):
                continue
            if tok.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                at_start = True
                continue
            if tok.type == tokenize.ENDMARKER:
                break
            if at_start:
                starts.append(tok.start)
                at_start = False
    except (tokenize.TokenError, IndentationError):
        pass
    return starts


def detect_newline(text: str) -> str:
    """Return the dominant newline style (``\\r\\n`` before a bare ``\\n``)."""
    crlf = text.find("\r\n")
    lf = text.find("\n")
    if crlf != -1 and (lf == -1 or crlf <= lf):
        return "\r\n"
    return "\n"


def leading_ws(line: str) -> str:
    """Return the leading spaces/tabs of ``line``."""
    index = 0
    while index < len(line) and line[index] in " \t":
        index += 1
    return line[:index]


def is_blank(line: str) -> bool:
    """True for lines that contain only whitespace (or nothing)."""
    return line.strip(" \t\r\n") == ""


def strip_eol(line: str) -> str:
    """Remove a trailing ``\\n`` / ``\\r\\n`` from ``line``."""
    return line.rstrip("\r\n")


def string_interior_lines(src: str) -> set[int]:
    """Return 1-based line numbers whose leading whitespace is inside a string.

    Indenting those lines would change the *value* of a multiline string, so
    structural edits must leave them untouched.  The check is deliberately
    conservative: for a multiline token, every line after its first line is
    treated as interior.
    """
    skip: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in _STRING_TOKENS and tok.start[0] != tok.end[0]:
                skip.update(range(tok.start[0] + 1, tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        pass
    return skip


def block_at_header(
    blocks: Iterable[Block], lineno: int, col: Optional[int] = None
) -> Optional[Block]:
    """Find the compound block whose header starts at ``lineno`` (and ``col``)."""
    matches = [b for b in blocks if b.lineno == lineno and (col is None or b.col == col)]
    if not matches:
        return None
    return min(matches, key=lambda b: (b.col, b.end_lineno))


def contains_block(outer: Block, inner: Block) -> bool:
    """True if ``inner`` is textually nested inside ``outer``."""
    return (
        outer is not inner
        and outer.lineno <= inner.lineno
        and inner.end_lineno <= outer.end_lineno
    )
