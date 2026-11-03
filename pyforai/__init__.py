"""pyforai — comment anchors and structural editing for AI-friendly Python.

Two layers:

* **L1** (:mod:`pyforai.checker`) validates ``# end <kind>`` anchors against
  the AST.  Anchors are assertions, not decoration.
* **L2** (:mod:`pyforai.editor`) performs structural edits (wrap, replace a
  body, move a block) that maintain indentation and anchors automatically.

The design principle is that authority lives in the toolchain, not in the
grammar: Python ignores the anchors, but ``pyforai`` treats a mismatch between
an anchor and the parser's structure as a hard error.
"""

from __future__ import annotations

from .anchors import ANCHOR_RE, KINDS, Anchor, Block, SourceModel, build_model
from .checker import CheckResult, Diagnostic, check_source
from .editor import EditError, EditResult, fmt, move, replace_body, wrap

__all__ = [
    "ANCHOR_RE",
    "KINDS",
    "Anchor",
    "Block",
    "CheckResult",
    "Diagnostic",
    "EditError",
    "EditResult",
    "SourceModel",
    "build_model",
    "check_source",
    "fmt",
    "move",
    "replace_body",
    "wrap",
]

__version__ = "0.1.0"
