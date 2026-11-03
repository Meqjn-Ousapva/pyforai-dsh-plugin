# pyforai — A DSH plugin that adds a checkable, addressable structure to Python

English | [中文](README.zh.md)

> pyforai is a DSH plugin for Python AI coding agents. Comment anchors are validated by `check` and used as block handles by `wrap` / `replace-body` / `move`.

```python
for item in items:
    if item.enabled:
        results.append(item.value)
    # end if
# end for
```

Python's parser ignores `# end if` / `# end for` entirely. That is the point: **no new syntax, no corpus lost**. But `pyforai` compares every anchor against the AST — a mismatch is a hard error.

That maps to two layers:

- **L1 `check`** treats anchors as assertions: it verifies them against the indentation, and the diagnostic names the kind and line it expects.
- **L2 `wrap` / `replace-body` / `move`** treats anchors as handles for structural edits, handling indentation automatically so the model no longer does whitespace surgery.

---

## DSH plugin

A structural editing and validation tool for Python AI coding. pyforai uses comment anchors to give Python code a checkable structural representation, solving the indentation drift and structural-transformation problems of AI coding. As a DSH plugin it exposes `pyforai_check` and `pyforai_edit` as two native tools, with `wrap`, `replace-body`, and `move` operations, so an AI agent can generate or refactor Python without hand-editing whitespace.

`dsh-plugin/` itself is a Host-only DSH bundle:

- `pyforai_check` — validate Python anchors, read-only; supports `strict` / `minLines` / `minDepth`.
- `pyforai_edit` — `fmt` / `wrap` / `replace_body` / `move`; automatic indentation, atomic writes.

Install into the current DSH profile:

```text
plugin_manager action=install_bundle target=/absolute/path/to/<repo>/dsh-plugin
```

Or from a shell: `dsh plugin --profile web add /absolute/path/to/<repo>/dsh-plugin`. See [DSH plugin install](#dsh-plugin-install-native-plugin) below for the difference.

Tool reference, config, reload, and sandbox notes: [`dsh-plugin/README.md`](dsh-plugin/README.md).

---

## What this project set out to do

pyforai did not start as a Python tool; it started as an exploration of a **language for AI programming**: if the primary reader is a model rather than a human, what should the syntax look like?

Python was the starting point because of corpus richness — models have seen the most of it and write it best, and any new syntax would trade that prior away. The cost is that Python's indentation was designed for humans and is machine-hostile. The obvious move is a Python dialect, for example `{}` instead of indentation — but that immediately loses compatibility with existing Python: parsers, formatters, linters, tests, and all existing code would have to change.

So the compromise is **comment anchors + tooling enforcement**: zero syntax change, no corpus lost; structural information lives in comments the parser already ignores, and `check` plus structural editing turn it into something checkable and addressable. This is an engineering compromise, not the optimal language design — and its ceiling comes from exactly this trade-off (see "What it solves, and what it doesn't" below).

---

## Why comments, not braces or a new dialect

Indentation has two real problems:

1. **Block structure is not addressable** — the token stream has no block boundaries and no names, so blocks can only be referred to by line number or text snippet.
2. **Structural changes are not local** — wrapping a block in `try` / `if` reindents the whole section, inflating the diff and drifting indentation.

Braces fix both halves at once, but the price is losing corpus and breaking toolchains. Comment anchors fix only the first half; the second half comes from structural editing (`wrap` / `replace-body` / `move`). That is why the approach is cheap, and why its ceiling is limited.

Three reasons for choosing Python all point at "don't touch the syntax":

- **Rich corpus**: any syntax extension trades prior knowledge for structure. Comments are the only channel in Python that is expressive yet completely ignored by the parser — zero syntax delta.
- **Glue, with room to sink**: Python is the orchestration layer with dense control flow — exactly where dedent semantics concentrate. Core modules can still move down to C/Rust/Go.
- **Fast feedback**: but silent indentation errors bypass it — the syntax is valid, tests may not cover it, and a formatter can freeze the wrong structure. Anchors pull those errors back into fast feedback.

---

## What it solves, and what it doesn't

| | Role of the anchor | Strength |
|---|---|---|
| Generation | One explicit commitment when closing a block; less "stack loss" | Weakly positive |
| Editing | Anchors alone do not reindent; pair them with `wrap` / `replace-body` / `move` | None |
| Validation | Turns "intent vs tokens" divergence into a detectable error | Medium |
| Representation | Blocks get handles: wrap/replace/move, searchable, reviewable | Strong |

One limitation must be stated clearly: **an anchor is a second sample of the same intent, not an independent checksum.** If the author's understanding of the structure and the indentation are wrong in the same place, the anchor is wrong in the same place too. It catches drift, not systematic misunderstanding. That is still valuable — drift dominates indentation incidents — but do not treat it as a formal proof.

---

## Advantages (data-backed)

In one line: the reliable advantages are **validation** and **output economy on large re-indents** — not "making a strong model fix code more correctly or faster".

- **Catches "syntactically valid but structurally wrong" drift**: E1 injects 592 syntactically valid drifts into 20 real files; `check` caught **476/476 (100%)**, `py_compile` missed all of them, and clean anchor files produced **0/165** false positives. `check --strict` separately caught 60/60 missing anchors (E010).
- **Localized diagnostics**: diagnostics sit 0–1 lines from the drift, and E001–E008 all hit their expected codes.
- **Large re-indents cut model output**: E2 wraps 20/80/200-statement `for` loops in `try/except`. At 200 statements the model-side payload drops from **15,940 B to 251 B (~63×)**; the three-size mean is 8,207 B → 296 B (~28×). What it saves is output tokens / context / cost — **wall-clock time does not improve**.
- **Controlled results**: all six E2 runs solved, the target AST matched the expected one, and there were 0 collateral changes outside the target block.

Conversely, the data does **not** support "helps a strong model fix code more correctly or faster" (E1 / E1.1 are at ceiling), and anchors are not a formal proof. The right positioning is a **CI / code-review structural-drift guard**, and **lower model output during large re-indents** — not "stronger automated repair". Full methodology, blind spots, and raw data: [`bench/SUMMARY.md`](bench/SUMMARY.md).

---

## Install

Standard library only, Python ≥ 3.10.

```bash
cd /path/to/pyforai-dsh-plugin
python -m pip install -e .
```

Or run it without installing:

```bash
python -m pyforai --help
```

---

## Go build (recommended for high-frequency calls)

`go/` holds a Go implementation of the same CLI: **a single static binary**, no Python/glibc dependency, about 1 ms to start.

```bash
make build          # bin/pyforai (host)
make static         # bin/pyforai-linux-amd64 + arm64 (static)
make test           # Go unit tests
sudo ./install.sh   # install to /usr/local/bin/pyforai
pyforai --version
```

Performance (100 runs on this machine, process startup included):

| Command | Python | Go | Speedup |
|---|---|---|---|
| `check examples/demo_good.py` | 50.3 ms | 1.36 ms | ~37× |
| `fmt --all --dry-run examples/demo_before.py` | 50.3 ms | 1.31 ms | ~38× |

`wrap` / `replace-body` default to `--python-check=auto` (runs CPython's `py_compile` for a full syntax check, ~31 ms per call when Python is available); `fmt` / `move` default to `off` (pure structural transforms, ~1.3 ms). Use `--python-check=on` for absolute safety, `off` for maximum speed.

Consistency: `go/oracle_check.py` compares the Go `check` against the Python version on 62 files in this project — currently **0 differences**; edit output on `examples/demo_*` is byte-identical to the Python version. Full notes: [`go/README.md`](go/README.md).

---

## DSH plugin install (native plugin)

`dsh-plugin/` is a Host-only DSH bundle that exposes `pyforai` as two native tools:

- `pyforai_check` — validate anchors, read-only; supports `strict`, `minLines`, `minDepth`.
- `pyforai_edit` — `fmt` / `wrap` / `replace_body` / `move`; automatic indentation and atomic writes, with `dryRun` support.

The plugin also registers a `tool:pyforai` system prompt: when generating or editing Python it calls `pyforai_edit` (starting new files with `fmt`, which anchors every multi-line block by default) and `pyforai_check`. Evaluation arms such as `no_check` can explicitly disable the prompt; the default is to follow it.

Install into the current profile (on this machine `web`, at `~/.dsh/profiles/web`):

```text
plugin_manager action=install_bundle target=/absolute/path/to/<repo>/dsh-plugin
```

Or install into the same profile from a shell (same result on disk):

```bash
# the path points at the bundle directory, not the repo root
dsh plugin --profile web add /absolute/path/to/<repo>/dsh-plugin
```

Both routes run the same `pnpm add` against the same profile manifest and `dsh.profile.bundles`, and a local directory is a `link:` dependency either way. The difference is activation: `install_bundle` applies the bundle synchronously inside the running Host and reports `applied` / `restart-required`; the CLI only writes the profile — a new bundle changes `dsh.profile.bundles`, so a running HMR usually recomposes on its own, while re-linking the same directory or only editing `index.js` leaves the list unchanged and needs a restart or a bundle toggle. The CLI also accepts a relative path (resolved from the current directory), but it does not refuse non-bundle packages and does not roll back the manifest and lockfile when pnpm itself fails.

The bundle ships static Linux amd64/arm64 binaries; relative paths resolve against the calling agent's session workspace. Row config:

```yaml
binaryPath: auto      # auto = binary inside the bundle; or an absolute path/command
pythonCheck: auto     # auto | on | off
timeoutMs: 30000
```

The source bundle is a link install: moving or deleting the checkout breaks the link, and after editing `index.js` you must toggle the bundle or restart the Harness to load the new Host module. Tool reference, reload steps, and sandbox notes: [`dsh-plugin/README.md`](dsh-plugin/README.md).

---

## 30-second quick start

```bash
# L1: validate
python -m pyforai check examples/demo_good.py
python -m pyforai check examples/demo_bad.py

# inspect without writing
python -m pyforai fmt --all --dry-run examples/demo_before.py

# L2: wrap the for loop in try
cp examples/demo_before.py /tmp/demo.py
python -m pyforai wrap /tmp/demo.py --header 6 --kind try \
    --except "Exception as e" --handler raise
```

`demo_bad.py` reports four self-correcting errors, for example:

```
examples/demo_bad.py:13:4: E001 kind mismatch: the block at column 4 is `for` (line 10), not `if`
  hint: the block ending here is `for` (opened at line 10); write `# end for`
examples/demo_bad.py:20:4: E003 the `if` at line 18 ends at line 22 (it continues into an `else`/`elif` clause); the anchor is inside it
  hint: move the anchor after line 22
```

---

## Anchor spec (summary)

Full spec: [`docs/SPEC.md`](docs/SPEC.md).

```python
# end if | for | while | try | with | def | class | match
```

Rules:

1. The anchor occupies its own line, at the same column as the block header.
2. Place it after the entire compound statement; `if/elif/else` and `try/except/else/finally` get one anchor after the whole statement.
3. Only comments or blank lines may sit between the block's last statement and the anchor.
4. One anchor per block; when nested, inner anchors come before outer ones.
5. **Use them sparsely**: write one when a block is long, deeply nested, or a dedent is easy to get wrong. Do not add them to three-line blocks.

`async def/for/with` normalize to `def/for/with`; there is no `# end async def`.

---

## L1: `check`

```bash
python -m pyforai check path/                 # recurse a directory
python -m pyforai check --strict path/        # also require anchors on "large/deep" blocks
python -m pyforai check --json path/          # structured output for agents
```

`--strict` thresholds:

```bash
python -m pyforai check --strict --min-lines 5 --min-depth 3 .
```

By default only anchors that are already written are validated; a missing anchor is not an error. `--strict` turns coverage into policy (`E010`).

Error codes:

| Code | Meaning |
|---|---|
| `E001` | kind mismatch (the block is `for`, the anchor says `if`) |
| `E002` | no block header at that column |
| `E003` | the anchor is inside the block (common before `else`/`except`) |
| `E004` | there is code between the block end and the anchor |
| `E005` | duplicate anchor |
| `E006` | the first code line after the anchor is deeper (defensive check) |
| `E007` | code precedes the anchor (not on its own line) |
| `E008` | an outer anchor appears before an inner one |
| `E010` | missing anchor in strict mode |
| `E100` | syntax error |

---

## L2: `wrap` / `replace-body` / `move`

Every edit command follows the same pipeline:

```
read -> parse -> validate existing anchors -> transform
     -> parse result -> validate result anchors -> atomic write
```

If any step fails, **nothing is written** and the file stays as it was. `--dry-run` only computes and prints a diff.

### `wrap`: wrap a block

```bash
# wrap the for loop whose header is on line 6 in try
python -m pyforai wrap demo.py --header 6 --kind try \
    --except "Exception as e" --handler raise

# wrap in if / with / for / while
python -m pyforai wrap demo.py --header 6 --kind if --condition "items"
python -m pyforai wrap demo.py --header 6 --kind with --context "lock"
python -m pyforai wrap demo.py --header 6 --kind for --target x --iterable xs
python -m pyforai wrap demo.py --header 6 --kind while --condition "ready"
```

- The new header goes at the target block's base indentation; the target block is indented one unit.
- The indent unit is inferred from the target block's own body (4 spaces / 2 spaces / tabs keep their style).
- Decorators move with `def/class`.
- Lines inside multiline strings are not re-indented; string values are unchanged.
- `# end <kind>` is added automatically.

### `replace-body`: replace a body

```bash
python -m pyforai replace-body demo.py --header 4 \
    --code 'return [item.value for item in items if item.enabled]'

# read from a file (handy for multi-line), or from stdin
python -m pyforai replace-body demo.py --header 4 --code-file body.py
python -m pyforai replace-body demo.py --header 4 --code-file -
```

- Replaces only the body of the target block's **first clause**: an `if`'s `elif/else` and a `try`'s `except` are preserved.
- Replacement code is dedented and then indented to the body.
- `--keep-docstring` keeps the original docstring (verbatim, not reindented).
- Single-line blocks (`if a: pass`) and `match` are refused with a reason.

### `move`: move a block

```bash
cp examples/demo_move.py /tmp/demo_move.py

# move the def second on line 8 before the def first on line 4
python -m pyforai move /tmp/demo_move.py --header 8 --before-line 4

# move after another statement
python -m pyforai move /tmp/demo_move.py --header 8 --after-line 4

# append to the end of the block body on line 4
python -m pyforai move /tmp/demo_move.py --header 8 --into-line 4
```

- The block moves together with its decorators, anchors, and trailing comments.
- Reindented to the target; relative indentation is preserved.
- Refused: moving into itself or a descendant, or moving away the only statement of a parent block (which would leave an empty body).
- **move is a syntax operation**; it does not check variable scope, control flow, or imports. Semantics are the caller's job.
- move does not handle blank lines/style; run black/ruff-format after large changes.

---

## What `fmt` is for (important)

```bash
python -m pyforai fmt --all --dry-run path/
python -m pyforai fmt --all path/
```

`fmt` does exactly one thing: insert anchors into blocks that **have none**.

- Insertion is inner-first; nested blocks ending on the same line are ordered by descending column, so the file reads inside-out.
- If the file already contains **invalid** anchors, `fmt` refuses to run. That is deliberate: silently "fixing" an assertion hides the bug it was meant to expose.
- **`fmt` inserts an AST mirror, not an assertion.** It improves readability and gives editors handles, but adds no validation value — it sees the same tree as the parser. Real validation value comes from writing anchors first and letting `check` compare them.

---

## Agent interface

```bash
python -m pyforai check --json .
python -m pyforai wrap demo.py --header 6 --kind try --except Exception --handler pass --json
python -m pyforai replace-body demo.py --header 4 --code-file - --json
python -m pyforai move demo.py --header 8 --into-line 4 --json
```

Conventions:

- `--json` prints a single object; `check` prints `{ok, errors, warnings, files}`.
- On failure `ok=false`, `diagnostics` carry `code/line/col/message/hint`, exit code 1.
- `--dry-run` returns a diff without writing, useful for "look before you leap".
- Line numbers are 1-based, columns 0-based (matching `ast`/`tokenize`).

It works directly as a CI / pre-commit gate:

```bash
python -m pyforai check --strict src/
```

---

## Design principles

1. **Authority lives in the toolchain, not the syntax.** Python ignores anchors; `pyforai` treats a mismatch as a hard error. That buys validation without forking the language.
2. **Anchors are optional and sparse.** The dual representation is a net burden on short blocks; write them only where they pay off.
3. **No whitespace surgery.** Structural editing (`wrap` / `replace-body` / `move`) owns reindentation; the model only says which block goes into what.
4. **Validate before writing.** The result must parse and pass the anchor check; otherwise the file stays untouched.
5. **Never touch multiline strings.** Accept visual misalignment rather than change a string value.
6. **Preserve encoding and line endings.** PEP 263 / BOM / CRLF / trailing newline are kept as-is where possible.

---

## Limitations (v0.1)

- No clause-level anchors (an `# end if` before `else`). `else`/`elif`/`except`/`finally`/`case` are already explicit boundary tokens.
- Cannot replace a `match` body, or move a block into `match`.
- Only compound statements can be moved, not single simple statements.
- move does no semantic checks (scope, imports, control flow).
- No blank-line/style normalization; run a formatter after large changes.
- Anchors are not an independent checksum (see "second sample" above).

---

## Tests

```bash
python -m unittest discover -s tests -v
```

There are currently 83 tests, covering: all block kinds, decorators, async, match, nested/sparse anchors, all 8 error classes, strict, JSON, CRLF, BOM, multiline strings, atomic writes, dry-run, fmt idempotence, and the success and refusal paths of wrap/replace/move.

---

## Repository layout

```
pyforai-dsh-plugin/
├── pyforai/           # Python reference implementation (spec/test oracle)
│   ├── anchors.py     # block model, anchor lexing, logical line starts
│   ├── checker.py     # L1: validation, diagnostics, strict, fmt planning
│   ├── editor.py      # L2: wrap / replace-body / move / fmt, atomic writes
│   └── cli.py         # CLI and JSON
├── go/                # Go build (recommended for frequent calls)
│   ├── scan.go        # lexer + block parser
│   ├── check.go       # L1
│   ├── edit.go        # L2 + atomic writes + diff + py_compile validation
│   ├── cli.go         # CLI / JSON
│   ├── cmd/pyforai/
│   └── README.md
├── dsh-plugin/        # DSH Host-only bundle: pyforai_check / pyforai_edit
│   ├── index.js       # native tools: spawn the binary, resolve workspace, render JSON
│   ├── cordis.patch.yml
│   ├── package.json
│   ├── locale/ icon.svg bin/
│   └── README.md
├── bin/               # make static output: pyforai-linux-amd64 / arm64
├── Makefile
├── install.sh
├── tests/             # unittest, no third-party dependencies
├── examples/
│   ├── demo_good.py   # passes check by default
│   ├── demo_bad.py    # four error classes
│   ├── demo_before.py # no anchors, used by the fmt/wrap demos
│   ├── demo_move.py   # used by the move demo
│   └── edge.py        # decorators/async/match/try-finally/for-else
├── docs/SPEC.md       # spec: lexing, positions, invariants, error codes, edit semantics
├── bench/             # evaluations: E1 validation / E1.1 repair / E2 structural editing
│   ├── SUMMARY.md     # data-backed capability summary
│   ├── README.md
│   ├── e1/            # drift + repair + e11
│   └── e2/            # forced-reindent wrap
└── pyproject.toml
```

---

## Evaluation (E1 / E1.1 / E2)

`bench/` currently holds three self-contained evaluations:

- **E1: validation.** 592 syntactically valid structural drifts injected into 20 real Python files, comparing `py_compile` with `pyforai check`. Result: `check` caught 476/476 with 0/165 false positives on clean anchor files; `py_compile` missed all of them.
- **E1.1: repair.** Single function, no `audit` twin, silent drift; comparing `no_check` / `tool_check` / `forced_diagnostic`. A strong model still fixed every case on the first try.
- **E2: structural editing.** Wrapping 20/80/200-statement `for` loops in `try/except`, comparing manual editing with `pyforai wrap`. At 200 statements the model-side output drops from 15,940 B to 251 B (~63×), though wall-clock time did not improve.

Full data and caveats: [`bench/SUMMARY.md`](bench/SUMMARY.md), [`bench/README.md`](bench/README.md).

## Keywords

DSH plugin, Python plugin, AI coding, AI coding agent, LLM, code anchors, comment anchors, structural editing, code indentation, refactor, code review, AST.

## Next steps

- **Lens mode**: keep the file pure Python on disk, inject anchors/block numbers on read, strip or structurally write back on save.
- **More structural operations**: extract-function, rename, import-aware move.
- **LSP / MCP**: expose `check`, `wrap`, `replace-body` to editors or agent runtimes.
- **Evaluation**: fill in real token counts, real 200-line code, `move` / `replace-body`, then decide whether E3 (real PR refactoring) is worth it. Structural refactoring is the main battlefield; if that class shows no significant gain, this direction should stop.
