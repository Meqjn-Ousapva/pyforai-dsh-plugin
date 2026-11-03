# pyforai anchor specification (v0.1)

This document is the normative description of the anchor syntax, the block
model, the validation invariants, and the structural edit semantics. The
implementation in `pyforai/` follows it; the tests in `tests/` are the
executable form of the important parts.

Conventions: source lines are **1-based**, columns are **0-based** (the same
convention as `ast` and `tokenize`). A "block" always means a *compound
statement*, never a suite inside an `if`/`try` clause.

---

## 1. Terms

| Term | Meaning |
|---|---|
| **anchor** | A comment of the form `# end <kind>`. Ignored by CPython. |
| **block** | A compound statement: `if`, `for`, `while`, `try`, `with`, `def`, `class`, `match`. |
| **header** | The first keyword of the block: `if`, `for`, `def`, ... |
| **body** | The suite of the block's first clause. |
| **close** | The structural position after the block's last statement (and after `else`/`elif`/`except`/`finally`/`case` clauses). |
| **derived anchor** | An anchor inserted by `fmt` from the AST. It mirrors the parse tree and therefore has no independent validation value. |
| **assertion anchor** | An anchor written by a human or model *before* the code is trusted. Its value comes from possibly disagreeing with the AST. |

---

## 2. Lexical form

```
anchor  ::= "#" ws* "end" ws+ kind ws* ( "#" any )?
kind    ::= "if" | "for" | "while" | "try" | "with" | "def" | "class" | "match"
```

Accepted:

```python
# end if
# end for
#end while
# end try  # optional note
```

Rejected as anchors (treated as ordinary comments):

```python
# end of file        # `of` is not a kind
# end iffy           # `iffy` is not a kind
# end if you want    # trailing prose is not allowed
# End if             # kinds are lowercase
```

Case sensitivity is deliberate: it keeps the convention aligned with Python
keywords and makes the token predictable in the training distribution.

---

## 3. Placement rules

An anchor **must** satisfy all of the following:

1. It is alone on its line: only whitespace precedes the `#`.
2. Its column equals the header column of the block it closes.
3. It appears after the block's last statement (`end_lineno < anchor line`).
4. Between `end_lineno` and the anchor there are only comment or blank lines
   (no logical line starts).
5. `# end if/elif/else` is placed after the **whole** `if` statement, including
   any `elif`/`else` clauses. The same applies to `try/except/else/finally`.
6. One anchor per block. A second anchor for the same block is `E005`.
7. If block A contains block B and both have anchors, B's anchor comes first.
8. The first code line after the anchor has column `<= anchor column` (or the
   file ends). This is a defensive invariant; valid Python rarely violates it.

Sparse use is the intended style:

> Write an anchor when the block is long, deeply nested, or at a dedent where a
> silent mistake is plausible. Do not annotate every three-line block.

`check --strict` turns this style guidance into a policy (`E010`) using two
thresholds: minimum block span (`--min-lines`, default 5) and minimum nesting
depth (`--min-depth`, default 3).

---

## 4. Block model

| AST node | kind | `end_lineno` covers |
|---|---|---|
| `If` | `if` | all `elif` / `else` clauses |
| `For`, `AsyncFor` | `for` | `else` clause, if any |
| `While` | `while` | `else` clause, if any |
| `Try`, `TryStar` | `try` | all `except` / `else` / `finally` clauses |
| `With`, `AsyncWith` | `with` | the whole `with` statement |
| `FunctionDef`, `AsyncFunctionDef` | `def` | the function body |
| `ClassDef` | `class` | the class body |
| `Match` | `match` | all `case` clauses |

For `def`/`class`, the *header* line is the `def`/`class` line. The first
physical line of the block (`first_line`) is the first decorator, if any. The
editor uses `first_line` when wrapping or moving so decorators travel with
their definition.

`async def`, `async for`, and `async with` normalise to `def`, `for`, and
`with`. There is no `# end async def`.

---

## 5. Validation invariants

Given a valid Python source `S` and an anchor `A` at `(line, col)`:

| # | Invariant | Violation |
|---|---|---|
| I1 | `A` is alone on its line | `E007` |
| I2 | A compound header exists at `col` | `E002` |
| I3 | The most recent such header has `end_lineno < A.line` (not inside it) | `E003` |
| I4 | No logical line starts between that header's `end_lineno` and `A.line` | `E004` |
| I5 | The header's kind equals `A.kind` | `E001` |
| I6 | The header is not already closed by another anchor | `E005` |
| I7 | The next logical line after `A` is at `col <= A.col`, or EOF | `E006` |
| I8 | Nested blocks are closed inner-first | `E008` |
| I9 | The source parses | `E100` |

Anchors are optional. A file with no anchors is valid under `check`. Under
`check --strict`, blocks meeting the coverage thresholds must have anchors
(`E010`).

The checker **never rewrites** anchors. `fmt` only inserts anchors for blocks
that do not have one; it refuses to run on a file whose existing anchors are
inconsistent.

---

## 6. Diagnostics

| Code | Meaning | Typical fix |
|---|---|---|
| `E000` | File could not be read/decoded (CLI only) | fix permissions/encoding |
| `E001` | Kind mismatch at this column | write the kind of the block that actually ends here, or move the anchor above the intervening sibling |
| `E002` | No compound header at this column | align the anchor with a header |
| `E003` | Anchor is inside the block (often before `else`/`except`) | move it after `end_lineno` |
| `E004` | Code between the block end and the anchor | move the anchor directly after the block |
| `E005` | Duplicate anchor | remove one |
| `E006` | Next code line is deeper than the anchor | the block does not end here |
| `E007` | Code before the anchor comment | put the anchor on its own line |
| `E008` | Outer anchor before inner anchor | close inner blocks first |
| `E010` | Strict mode: missing anchor | add it, or run `fmt` |
| `E100` | Syntax error | fix the syntax first |

Every diagnostic carries `line`, `col`, `message`, `hint`, `code`, and
`severity`. The hint is written to be directly actionable by a model: it names
the expected kind/line rather than only saying "invalid".

---

## 7. JSON output

`check --json`:

```json
{
  "ok": false,
  "errors": 1,
  "warnings": 0,
  "files": [
    {
      "path": "foo.py",
      "ok": false,
      "anchors": 2,
      "diagnostics": [
        {
          "code": "E001",
          "severity": "error",
          "line": 13,
          "col": 4,
          "message": "kind mismatch: ...",
          "hint": "the block ending here is `for` ..."
        }
      ]
    }
  ]
}
```

Edit commands (`wrap`, `replace-body`, `move`, `fmt`) with `--json` return:

```json
{
  "ok": true,
  "path": "foo.py",
  "operation": "wrap",
  "changed": true,
  "detail": "wrapped `for` at line 4 in `try`",
  "diff": "--- a/foo.py\n+++ b/foo.py\n...",
  "diagnostics": []
}
```

Failures return `{"ok": false, "error": "...", "diagnostics": [...]}` and exit
code 1.

---

## 8. Structural edit semantics

All edits follow the same pipeline:

```
read -> parse -> validate existing anchors -> transform
     -> parse result -> validate result anchors -> atomic write
```

If any step fails, the original file is untouched. `--dry-run` stops before the
write but still computes and validates the result.

### 8.1 `wrap`

Wrap the target block (including its decorators and its existing anchor) in a
new construct.

- The new header is placed at the target block's base indentation.
- Every line of the target block is indented by the target block's own
  indentation step (inferred from its body, so tabs/2-space/4-space files keep
  their style).
- The wrapper's closing anchor is appended at the base indentation.
- Supported kinds: `try`, `if`, `with`, `for`, `while`.
- `try` requires an `except` clause (default `Exception`) and a handler body
  (default `raise`).
- Lines whose leading whitespace is inside a multiline string are **not**
  reindented. This preserves string values at the cost of visual alignment;
  a formatter can adjust the surrounding code.

### 8.2 `replace-body`

Replace the body of the target block's **first clause**.

- `if`/`elif`/`else`: only the `if` clause's body is replaced; `elif`/`else`
  remain.
- `try`: only the `try` clause's body is replaced; handlers remain.
- `for`/`while`: only the loop body is replaced; `else` remains.
- `def`/`class`: the whole body (including methods) is replaced.
- `match` is rejected: "the body" of a `match` is a list of `case` clauses,
  which is not a suite. Target a case body instead.
- A one-line block (`if a: pass`) is rejected: the body shares the header line.
- The replacement code is dedented, then indented to the block's body level.
- Docstrings: `--keep-docstring` preserves the existing docstring (lines are
  kept verbatim, not reindented); otherwise it is removed and `detail` says so.

### 8.3 `move`

Move a compound block. Destinations:

| Destination | Meaning |
|---|---|
| `--before-line L` | before the statement/block starting at `L`, at its indentation |
| `--after-line L` | after the statement/block starting at `L`, at its indentation |
| `--into-line L` | append to the end of the body of the block starting at `L` |

- The moved span includes decorators, the block's anchor, and trailing
  comment-only lines indented inside the block.
- The block is reindented by replacing its base prefix with the destination
  prefix; relative indentation is preserved. Multiline string interiors are
  skipped.
- Rejected: destination inside the moved span, moving a block into itself or a
  descendant, moving the only statement out of a parent (which would leave an
  empty suite).
- Moving a block is a **syntactic** operation. It does not check variable
  scope, control flow, or imports. The caller is responsible for semantics.

### 8.4 `fmt`

Insert anchors for blocks that lack them.

- Selection: `--all` inserts for every multi-line block; otherwise blocks with
  span `>= --min-lines` or depth `>= --min-depth`.
- Ordering: inner blocks first. For blocks ending on the same line, larger
  columns are inserted first so the file reads inner-to-outer.
- `fmt` refuses to run if existing anchors are invalid. This is deliberate:
  silently "fixing" an assertion would hide the bug the assertion was meant to
  expose.
- `fmt` anchors are **derived** from the AST. They improve readability and give
  editors handles, but they cannot detect a wrong dedent, because they were
  generated from the same parse tree. Real validation requires anchors written
  before the code is trusted.

---

## 9. Safety properties

- **Atomic write**: temp file in the same directory, `fsync`-free but
  `os.replace`; original mode preserved.
- **Validate before write**: the result must parse and pass `check` (non-strict).
- **Encoding**: PEP 263 / BOM detection via `tokenize.detect_encoding`; the
  original encoding is used for writing.
- **Line endings**: the dominant newline (`\r\n` or `\n`) is preserved, as is
  the presence/absence of a final newline.
- **Multiline strings**: interior lines are never reindented.

---

## 10. Non-goals and limitations (v0.1)

- Clause-level anchors (`# end if` before `else`). `else`/`elif`/`except`/
  `finally`/`case` are already explicit boundary tokens; supporting clause
  anchors would complicate the invariant for little gain.
- Replacing a `match` body, or moving a block into a `match`.
- Moving simple statements (only compound blocks can be targets).
- Semantic validation of moves (scope, imports, control flow).
- Style/blank-line normalisation. Run a formatter after large moves.
- An independent checksum. The anchor is a *second correlated sample* of the
  author's structural intent, not independent evidence. It catches drift
  between the stated structure and the lexical structure; it does not catch a
  misunderstanding shared by both.

---

## 11. Versioning

`v0.1` is the initial implementation. The anchor grammar is intentionally small;
additions should preserve the ability of existing Python tooling to ignore
anchors completely.
