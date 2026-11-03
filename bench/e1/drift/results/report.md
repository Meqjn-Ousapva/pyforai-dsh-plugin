# E1 drift report

Generated: 2026-11-03T14:59:25+0800

## Headline

- Cases: **592** across **20** files.
- Check detection: **476/476** (100.0%) of syntax-valid drifts.
- Strict-mode detection: **536/536** (100.0%), including deleted anchors (E010).
- Expected diagnostic matched: **588/592** (99.3%).
- Clean-file false positives: **0/165**.

`py_compile` accepts 100% of these cases by construction; the comparison is
the point: every drift below is syntax-valid Python that a test-free
syntax check cannot see.

## By drift class

| drift | n | detected | rate | strict | mean diag distance | codes |
|---|---|---|---|---|---|---|
| kind_mismatch | 60 | 60/60 | 100.0% | 60/60 | 0.0 | E001:60 |
| wrong_column | 60 | 60/60 | 100.0% | 60/60 | 0.0 | E002:60 |
| inside_block | 60 | 60/60 | 100.0% | 60/60 | 0.0 | E003:60 |
| not_adjacent | 60 | 60/60 | 100.0% | 60/60 | 1.0 | E004:60 |
| duplicate | 60 | 60/60 | 100.0% | 60/60 | 1.0 | E005:60 |
| trailing_code | 60 | 60/60 | 100.0% | 60/60 | 0.0 | E007:60 |
| outer_before_inner | 58 | 58/58 | 100.0% | 58/58 | 0.1 | E005:4, E008:54 |
| dedent_last | 58 | 58/58 | 100.0% | 58/58 | 0.0 | E004:58 |
| missing_anchor | 60 | 0/0 | — | 60/60 | — | — |
| consistent_shift | 56 | 0/0 | — | 0/0 | — | — |

## Formatter interaction (pyforai 0.2.0 Go, black 26.10.1)

| metric | value |
|---|---|
| files | 20 |
| `pyforai fmt` exit 0 | 20 |
| ... and result passes check | 20 |
| ... and result passes strict | 18 |
| second `pyforai fmt` is idempotent | 18 |
| black exit 0 (after successful fmt) | 20 |
| check passes after black | 20 |

Two files fail `check --strict` after `fmt`: `repo_pyforai_cli_py` and
`stdlib_shutil_py` contain a block that `fmt` leaves unanchored but strict
demands.  This is a coverage inconsistency between sparse `fmt` and strict
mode, not a drift-detection failure.

`fmt` inserts derived anchors; `fmt` → `check` is tautological.  A file that
`fmt` cannot process would be a tool failure, but none remain on this corpus.

### Black on drifted cases (3 samples per class)

| drift | n | AST changed | detected before | detected after black | masked |
|---|---|---|---|---|---|
| kind mismatch | 3 | 0 | 3 | 3 | 0 |
| wrong anchor column | 3 | 0 | 3 | **0** | **3** |
| anchor inside block | 3 | 0 | 3 | 3 | 0 |
| sibling before anchor | 3 | 0 | 3 | 3 | 0 |
| duplicate anchor | 3 | 0 | 3 | 3 | 0 |
| code before anchor | 3 | 0 | 3 | 3 | 0 |
| outer before inner | 3 | 0 | 3 | 3 | 0 |
| dedented last statement | 3 | 0 | 3 | 3 | 0 |
| missing anchor | 3 | 0 | 0 | 0 | — |
| consistent shift | 3 | 0 | 0 | 0 | — |

`black` re-indents a misplaced anchor back to the header column.  The code is
still wrong, but `check` after `black` is clean.  Run `check` before a
formatter, or check the pre-format file.

## Injection failures

382 attempted (block, drift) pairs could not be
injected without a syntax error or without producing the expected code.
These are generator coverage limits, not checker results.

