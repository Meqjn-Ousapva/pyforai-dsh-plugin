# E1.1 findings (2026-11-03)

E1.1 removes the `process`/`audit` twin that confounded E1's repair pilot.  The
source is a single `process` function with 32 record kinds; each task is a
**silent** drift (public tests pass, hidden tests fail).  Twelve runs: 4 tasks
x 3 diagnostic arms.

## Result: still a ceiling

| arm | n | solved | first try | mean first edit s | mean wall s | payload B | check used | anchors moved |
|---|---|---|---|---|---|---|---|---|
| `no_check` | 4 | 4/4 | 4/4 | 15.5 | 30.5 | 168 | 0/4 | 0 |
| `tool_check` | 4 | 4/4 | 4/4 | 11.8 | 25.5 | 168 | 4/4 | 0 |
| `forced_diagnostic` | 4 | 4/4 | 4/4 | 18.0 | 28.2 | 168 | 0/4 | 0 |

All runs repaired on the first attempt, with no failed test run.  No anchors
were moved; no laundering.  `tool_check` is ~4 s faster to first edit than
`no_check`, but N=4, one forced run took 50 s, and the direction is not stable.
`forced_diagnostic` (check output pre-written to `diagnostics.md`, no tool call)
was not faster than either arm.

**Interpretation:** the diagnostic was useful but not necessary.  A strong
model can localise these drifts from the single `# end if` anchor and the
`else: pass` residue left by the hoist.  The task is still too easy, not the
model too weak.

## Why the task is still easy

* Each task has exactly **one anchor**, placed on the drifted block.  The
  anchor itself points at the answer; `check` only formalises the observation.
* The `hoist_else` drift leaves a visible `else: pass` and a line sitting
  between the block end and the anchor.  A careful reader can see it without
  running anything.
* The file is large (200+ lines), but the drift is a single local hunk.

## What to change for E1.2

1. **Multi-anchor start files.**  Put 8–15 anchors in the file, only one of
   which is involved in the drift.  Then `check` has to select the right one;
   the anchor itself no longer localises the answer.
2. **No residue.**  Use a drift that does not leave a placeholder `pass` or an
   obviously orphaned line (e.g. a dedent of one statement from a multi-statement
   body), or normalise the residue away.
3. **Weaker model or tighter budget.**  The strong model is at ceiling on this
   task family.  A 3B/7B local model or a hard token/turn budget is needed to
   see whether the diagnostic changes behaviour.
4. **Token instrumentation.**  `payload B` is identical because every repair is
   a one-line edit.  It cannot show the cost of *finding* the line.  The runner
   should log prompt/completion tokens; until then, wall/first-edit time is the
   only available localisation cost.

## What E1.1 did validate

* The harness: single-function tasks, silent drift, hidden-only failure,
  three arms, forced-diagnostic file, first-edit timestamp, anchor fingerprint,
  compliance, and report aggregation.
* The `forced_diagnostic` arm can be run with **zero** tool calls, so it cleanly
  separates "diagnostic content" from "tool invocation".
* No anchor tampering or laundering in any arm.

## Bottom line

Removing the twin fixed the confound but not the ceiling.  The next useful
experiment is not another strong-model run; it is **multi-anchor tasks plus a
weak/medium model**.  Without one of those, E1.2 will produce another precise
"all solved".
