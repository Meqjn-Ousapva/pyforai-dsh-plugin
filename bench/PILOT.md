# Pilot results and analysis

Generated from `bench/runs/*/metrics.json` after nine runs (3 tasks × 3 arms,
one run per cell) executed by DSH subagents on 2026-11-03.

## Headline

**All nine runs passed both public and hidden tests on the first attempt; no run
needed a repair.** This is a ceiling effect: the tasks are below the difficulty
at which indentation/structural errors appear, so the pilot cannot test the
correctness hypothesis (H1).

The cost result is more interesting than the correctness result:

> **A (plain) < C (anchors + structural editing) < B (hand-written anchors)** on
> mean wall time. Hand-maintaining anchors is more expensive than letting the
> tool maintain them. A is still the cheapest because, at this difficulty, it is
> just as correct.

## Measurements

| task | arm | public | hidden | anchor err | anchors | LOC | diff +/- | test runs | repairs | wall s | pyforai ops+help |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1_retry_loop | A | yes | yes | 0 | 0 | 21 | 9/4 | 1 | 0 | 10 | 0+0 |
| R1_retry_loop | B | yes | yes | 0 | 4 | 24 | 11/4 | 1 | 0 | 60 | 1+0 |
| R1_retry_loop | C | yes | yes | 0 | 8 | 28 | 15/4 | 1 | 0 | 58 | 6+6 |
| R2_reconcile | A | yes | yes | 0 | 0 | 37 | 10/7 | 1 | 0 | 6 | —+— |
| R2_reconcile | B | yes | yes | 0 | 6 | 43 | 16/7 | 1 | 0 | 81 | 3+3 |
| R2_reconcile | C | yes | yes | 0 | 1 | 38 | 11/7 | 1 | 0 | 16 | 2+0 |
| W1_retry | A | yes | yes | 0 | 0 | 31 | 39/0 | 2 | 0 | 16 | 0+0 |
| W1_retry | B | yes | yes | 0 | 6 | 62 | 70/0 | 1 | 0 | 74 | 2+0 |
| W1_retry | C | yes | yes | 0 | 8 | 45 | 55/0 | 2 | 0 | 57 | 4+0 |

Aggregate:

| arm | condition | n | public | hidden | anchor err | anchors | LOC | diff | repairs | wall s | success/min | pyforai ops+help |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | no anchors | 3 | 3/3 | 3/3 | 0.0 | 0.0 | 29.7 | 23.0 | 0.0 | 10.7 | 5.62 | 0.0+0.0 |
| B | anchors | 3 | 3/3 | 3/3 | 0.0 | 5.3 | 43.0 | 36.0 | 0.0 | 71.7 | 0.84 | 2.0+1.0 |
| C | anchors + structural editing | 3 | 3/3 | 3/3 | 0.0 | 5.7 | 37.0 | 30.7 | 0.0 | 43.7 | 1.37 | 4.0+2.0 |

`success/min` = hidden passes / total wall-clock minutes. `diff` = added +
removed lines against `start.py` (write tasks: against an empty file).

## Reading the numbers

### Correctness: ceiling

A = B = C = 3/3. **H1 is untested.** The tasks range from 21 to 62 LOC and from
a 5-line refactor to an 8-line, 3-level reindent. The model handles all of them
without a repair. A harder task (R2) did not break the ceiling; it only made the
cost differences larger.

This is the most important negative result: **if the baseline never fails, the
intervention cannot show a correctness benefit.** The pilot must be made harder
before it can test the hypothesis.

### Cost: A < C < B

Mean wall time:

- A: 10.7 s
- C: 43.7 s
- B: 71.7 s

The ordering C < B is the opposite of the naive "tooling adds overhead" story.
The structural tool *replaces* the most expensive part of the anchor workflow:
manual reindentation and hand-maintained anchors.

The clearest case is R2, the largest refactor:

- A: 6 s, manual reindent, no anchors.
- C: 16 s, one `wrap` + one `check`, one anchor, clean diff.
- B: 81 s, hand-written anchors for six blocks, extra `check --strict`, and
  deliberation about which headers to anchor.

On R2, C is ~5× faster than B and only ~2.7× slower than A. That is the first
signal in the pilot that structural editing can pay for itself — on a large
enough reindent, when the alternative is hand-maintaining anchors.

R1 and W1 are noisier:

- R1: C 58 s vs B 60 s. C's 12 calls are **6 actual operations + 6 `--help`**;
  `fmt --all` over-anchored the file (8 anchors). The over-anchoring inflated
  C's LOC/diff.
- W1: B 74 s / 62 LOC is an outlier driven by docstrings/prose, not anchors;
  C 57 s / 45 LOC used `fmt` for anchors.

The aggregate still favors C over B, but N=1 per cell means this is a hypothesis,
not a result.

### `--help` is a CLI integration artifact

`pyforai` is invoked through bash, so its flags are not in the agent's native
tool schema. R1 C ran the top-level help plus each subcommand's help (6 calls)
before doing 6 real operations. This is not specific to C: R2 B ran 3 help calls
when it went looking for `fmt`/strict options, and R2 C needed none because the
`wrap` example in the arm prompt was enough. The variance is discovery, not
workflow. A DSH tool with a JSON schema (or a skill with a command card) would
remove most of it.

The help calls are cheap in wall time (CLI startup is milliseconds), but they
inflate a naive call count. The `ops+help` split keeps the tool-cost comparison
honest: C averages 4.0 ops + 2.0 help, B averages 2.0 ops + 1.0 help. C still
does more real operations because it runs `check` after each structural edit;
that is the intended workflow, not overhead.

### Artifact size

A < C < B on LOC (29.7 / 37.0 / 43.0) and diff (23.0 / 30.7 / 36.0). B's
hand-written anchors and prose cost more lines than C's tool-generated anchors.
C's R1 `fmt --all` over-anchored, which is a fixable instruction bug, not a tool
property.

### Compliance

- A: 0 anchors, 0 pyforai calls — as instructed.
- B: 4–6 hand-written anchors, 0 anchor errors, only `check` used — as instructed.
- C: 1–8 anchors, 0 errors, used `replace-body` (R1), `fmt` (W1), `wrap` (R2) —
  as instructed.
- No `tests_public.py` tampering in any run.

The arms were executed as intended, so the null correctness result is not a
compliance artifact.

### The R2 structural edit is correct

R2's `if account.active:` body is the `for entry in ledger.get(...)` loop. C
targeted the `for` (header 34) with `wrap --kind try`, which keeps the `else`
branch outside the try. This is exactly the intended structure. The tool's
whole-statement semantics require targeting the body statement, not the `if`; C
did that. The result has one anchor (`# end try`) and a clean diff. This is a
usability note for the docs, not a defect.

## Efficiency

At this difficulty:

- **A is the most efficient**: 5.62 hidden passes per wall-minute, lowest LOC and
  diff. The intervention is pure overhead when the baseline already passes.
- **C is more efficient than B** (1.37 vs 0.84 passes/min): if anchors are used,
  tool-maintained anchors are cheaper than hand-maintained ones. This supports
  the "authority in the toolchain" design.
- The value case for C is not speed on easy tasks; it is (a) eliminating manual
  anchor maintenance and (b) potentially preventing errors on tasks where the
  baseline starts to fail. (b) is untested.

## What the pilot changes in the design

1. **Difficulty calibration first.** Run A on a staircase of harder tasks until
   its hidden-pass rate is roughly 50–70%; then compare B/C at that difficulty.
   Fixed easy tasks produce a ceiling and no signal.
2. **Harder task family.** 100+ line functions, 4+ nesting levels, multi-block
   wraps/moves, cross-function refactors, longer context. R2's 8-line reindent is
   still too easy; it only widened the cost gap.
3. **Fix the C arm instruction.** Use `fmt --min-lines 5 --min-depth 3`, not
   `--all` (which overrides the threshold).
4. **Measure tokens/usage, not only wall time.** Wall time conflates reasoning,
   tool latency, and model speed. Add a `usage.json` emitted by the agent
   adapter (prompt tokens, completion tokens, tool calls).
5. **Make "tool-maintained anchors" a first-class comparison.** The pilot's most
   interesting result is C < B on cost. A follow-up should compare
   "hand anchors" vs "fmt/check anchors" directly, with the same code edits.
6. **More runs.** Paired tasks (20–30) or ~55 runs/arm for a 25-point independent
   difference. N=1 is a smoke test.
7. **Neutral wording / blind evaluation.** The arm rules may cue the agent that
   anchors are "supposed" to help; reduce demand effects.

## Bottom line

The pipeline works, the arms were executed as intended, and the cost measurement
is usable. The correctness result is uninformative because of the ceiling. The
next experiment must first find the difficulty where A fails, then compare B and
C at that difficulty.

Until then, the pilot supports two claims:

> 1. On small, familiar Python tasks, anchors and structural editing add cost
>    without a measurable correctness benefit.
> 2. If anchors are used at all, tool-maintained anchors (C) are cheaper than
>    hand-maintained anchors (B), especially on larger reindents.
