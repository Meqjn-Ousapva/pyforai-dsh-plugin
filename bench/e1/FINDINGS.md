# E1 findings (2026-11-03)

This is the first E1 run.  It is an internal decision aid, not a powered study.
Raw outputs: [`drift/results/report.md`](drift/results/report.md),
[`repair/results/report.md`](repair/results/report.md).

## What was measured

* **Product binary:** `pyforai 0.2.0 (go)`, from `/usr/local/bin/pyforai`
  (the same implementation the DSH plugin ships).  The Python reference was
  used only to generate cases and as a cross-check; on all 592 drift cases the
  Go and Python checkers agreed on detection and diagnostic codes.
* **Corpus:** 20 real Python files (12 CPython 3.12 stdlib, 8 this repo),
  vendored with a SHA-256 manifest.
* **Drift suite:** 592 cases.  Each picks a block, inserts one anchor, injects
  one syntax-valid drift, and compares `py_compile` with `pyforai check`.
* **Repair pilot:** 12 agent runs (3 tasks x 2 modes x 2 arms).  `check_on`
  runs `pyforai check`; `check_off` is told not to.  Both arms see the same
  anchors and tests.

## Drift detection: the checker works

| metric | result |
|---|---|
| Syntax-valid drifts detected | **476 / 476 (100%)** |
| Clean anchored files with a false positive | **0 / 165** |
| Deleted anchors caught by `check --strict` | **60 / 60 (E010)** |
| `py_compile` detection | **0%** by construction |
| Diagnostic within 0 lines of the anchor | most classes; `not_adjacent`/`duplicate` mean 1.0 |

By class:

| drift | n | detected | code |
|---|---|---|---|
| kind mismatch | 60 | 60 | E001 |
| wrong anchor column | 60 | 60 | E002 |
| anchor inside block | 60 | 60 | E003 |
| sibling inserted before anchor | 60 | 60 | E004 |
| duplicate anchor | 60 | 60 | E005 |
| code before anchor | 60 | 60 | E007 |
| outer anchor before inner | 58 | 58 | E008 (4 cases also/instead E005) |
| last statement dedented out | 58 | 58 | E004 |
| anchor deleted | 60 | 0 non-strict; 60 strict | E010 |
| anchor moved with the code | 56 | **0** | blind spot by design |

The last row is the checker's known limitation: if the edit moves the anchor
consistently with the code, there is no disagreement to detect.  It is reported
separately, never counted as a detection success.

**Interpretation:** for the mechanism it claims to provide, the checker is
reliable on this corpus.  A syntax check cannot see block ownership; this one
can, locates the anchor line, and does not fire on clean anchored files.

## Formatter interaction: two real defects

`fmt` inserts *derived* anchors, so `fmt` → `check` is tautological.  The
interesting questions are whether `fmt` runs at all and whether a formatter
can launder a drift.

| metric | result |
|---|---|
| `pyforai fmt` exit 0 | 20 / 20 |
| result passes `check` | 20 / 20 |
| result passes `check --strict` | **18 / 20** |
| second `fmt` is idempotent | 18 / 20 |
| black exit 0 on successful fmt | 20 / 20 |
| `check` passes after black | 20 / 20 |

The two strict failures are a **coverage inconsistency**: `fmt` leaves a block
unanchored that `check --strict` demands (e.g. `repo_pyforai_cli_py` line 261,
`stdlib_shutil_py` line 1359; both `if` blocks with span 5, depth 2).  This is
not a drift-detection failure, but it means `fmt --min-lines 5 --min-depth 3`
followed by `check --strict` is not a stable workflow today.

While building the suite we also found two Python-reference defects and fixed
them with regression tests:

* `fmt` emitted duplicate anchors for `elif` chains (E005);
* `check --strict` demanded a separate anchor for the nested `elif` node,
  which the outer `if` anchor already covers (E010 on a valid fmt result).

The Go binary already handled the `elif` cases correctly; the Python fixes make
the two implementations agree.

### Black can launder anchor drift

`black` on the drifted cases:

| drift | n | AST changed | detected before | detected after black | masked |
|---|---|---|---|---|---|
| wrong anchor column | 3 | 0 | 3 | **0** | 3 |
| other anchor/code drifts | 21 | 0 | 21 | 21 | 0 |
| missing anchor | 3 | 0 | 0 | 0 | — |
| consistent shift | 3 | 0 | 0 | 0 | — |

`black` re-indents a misplaced anchor back to the header column.  The code is
still wrong, but `check` after `black` is clean.  **Run `check` before a
formatter**, or use `check` on the pre-format file; otherwise formatting can
turn an assertion into decoration.

## Repair pilot: ceiling, and a task-design confound

| arm | n | solved | public+hidden | anchors moved | laundered | check used | mean wall s |
|---|---|---|---|---|---|---|---|
| `check_on` | 6 | 6/6 | 6/6 | 0 | 0 | 5/6 | 32.2 |
| `check_off` | 6 | 6/6 | 6/6 | 0 | 0 | 0/6 | 45.7 |

All 12 runs repaired the file on the **first** attempt.  No anchors were
edited, so there was no laundering.  `check_on` did not always use `check`
(one T8 run solved from tests alone).  The silent mode — public tests green,
hidden tests fail — did not separate the arms either.

Two reasons the pilot is uninformative about the value of `check`:

1. **The drift is easy once seen.**  `return report` dedented out of an early
   return is visible from the test failure; `report["matched"] += 1` hoisted
   out of an `else` is visible by comparing `process` with `audit`.
2. **The reference has a free oracle.**  `process` and `audit` are
   near-identical twins.  A control agent can diff them to locate a drift in
   `process`.  This is a task-design confound, not evidence about `check`.

The pilot does show the harness works: public/hidden scoring, anchor
fingerprints, per-edit snapshots, `check` call counts, and laundering detection
all behave as intended.

## What this means for the internal decision

* **Keep `check` as a verification primitive.**  It catches the drift classes
  we can generate, has no false positives on the corpus, and points at the
  anchor line.  That is enough to justify using it in CI or review, where the
  question is "did this edit change block ownership?" rather than "is the code
  correct?".
* **Do not claim a productivity gain yet.**  The repair pilot is at a ceiling;
  strong models localise and fix these drifts with or without `check`.  There
  is no evidence here that `check` reduces repair attempts or tokens.
* **Do not treat `anchor_errors = 0` after `fmt` as a quality signal.**  `fmt`
  derives anchors from the AST; the check is self-confirming.  Only assertion
  anchors written before the edit carry independent information.
* **Fix the `fmt`/strict coverage gap** before making `fmt --strict` part of a
  workflow.  The two failing files show the sparse policy and strict coverage
  disagree.
* **Run `check` before formatting.**  `black` can silently repair a misplaced
  anchor and hide the drift.

## Next steps

1. **E1.1 repair:** single-function reference (no `process`/`audit` twin),
   weaker or faster model, and a drift in a branch the public tests do not
   exercise.  The outcome to measure is *time/tokens to localise*, not just
   solved/not solved.
2. **E2 editing:** forced-reindent tasks (large blocks, no `else:`-reuse
   shortcut), arms for plain+black, formatter-only, native plugin, and an AST
   tool; primary metrics are output tokens, collateral AST changes, and
   structural success.  E1 does not test `wrap` / `move` / `replace-body`.
3. **Instrumentation:** log token usage and per-edit snapshots from the runner,
   not from agent self-reports.  The current `edit_payload_bytes` is a proxy.
