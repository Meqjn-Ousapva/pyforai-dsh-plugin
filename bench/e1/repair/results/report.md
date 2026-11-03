# E1 repair report

Generated: 2026-11-03 15:08:14

> Small pilot: two drift modes (visible and silent), one reference family, and
> a small number of runs.  It validates the harness and gives a direction; it is
> not a powered comparison.

## Per run

| task | mode | fn | arm | solved | public | hidden | anchors moved | anchor err | check calls | failed attempts | wall s | payload B |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1_pipeline__process__dedent_last__01 | visible | process | check_off | yes | yes | yes | no | 0 | 0 | 0 | 20 | 42 |
| T1_pipeline__process__dedent_last__01 | visible | process | check_on | yes | yes | yes | no | 0 | 2 | 0 | 14 | 42 |
| T1_pipeline__process__silent__hoist_else__01 | silent | process | check_off | yes | yes | yes | no | 0 | 0 | 0 | 23 | 134 |
| T1_pipeline__process__silent__hoist_else__01 | silent | process | check_on | yes | yes | yes | no | 0 | 2 | 0 | 27 | 134 |
| T4_pipeline__process__dedent_last__01 | visible | process | check_off | yes | yes | yes | no | 0 | 0 | 0 | 13 | 42 |
| T4_pipeline__process__dedent_last__01 | visible | process | check_on | yes | yes | yes | no | 0 | 3 | 0 | 49 | 42 |
| T4_pipeline__process__silent__hoist_else__01 | silent | process | check_off | yes | yes | yes | no | 0 | 0 | 0 | 156 | 134 |
| T4_pipeline__process__silent__hoist_else__01 | silent | process | check_on | yes | yes | yes | no | 0 | 3 | 0 | 24 | 134 |
| T8_pipeline__process__dedent_last__01 | visible | process | check_off | yes | yes | yes | no | 0 | 0 | 0 | 21 | 42 |
| T8_pipeline__process__dedent_last__01 | visible | process | check_on | yes | yes | yes | no | 0 | 0 | 0 | 20 | 42 |
| T8_pipeline__process__silent__hoist_else__01 | silent | process | check_off | yes | yes | yes | no | 0 | 0 | 0 | 41 | 134 |
| T8_pipeline__process__silent__hoist_else__01 | silent | process | check_on | yes | yes | yes | no | 0 | 3 | 0 | 59 | 134 |

## Aggregate

| arm | n | solved | behavior only | anchors moved | laundered | check used | attempts | wall s | payload B | edits |
|---|---|---|---|---|---|---|---|---|---|---|
| check_on | 6 | 6/6 | 6/6 | 0 | 0 | 5/6 | 0.0 | 32.2 | 88.0 | 1.0 |
| check_off | 6 | 6/6 | 6/6 | 0 | 0 | 0/6 | 0.0 | 45.7 | 88.0 | 1.0 |

``solved`` = public + hidden pass, no anchor edited, and final ``check`` clean.
``behavior only`` ignores the anchor constraint.
``anchors moved`` is a position-independent comparison of every ``# end`` line.
``laundered`` means anchors changed and the final ``check`` is clean: the agent
made the checker agree by editing the assertion, not the code.
``payload B`` is the sum of added/removed bytes across the per-edit snapshots;
it is a proxy for output tokens, not a token count.

## Caveats

- N is small; treat differences as hypotheses.
- ``check_off`` compliance is prompt-level, not sandbox-level: the arm is told
  not to use ``pyforai``, and the score records whether it did.
- Attempts, wall time and snapshots are self-reported by the agent.  The
  public/hidden results and the anchor fingerprint are computed by the harness.
- ``visible`` drifts make the public tests fail; ``silent`` drifts leave the
  public tests green and fail only the hidden tests.  The silent mode is the
  one that can distinguish "check locates the drift" from "the tests already
  localise it".
- Both modes use the same `process`/`audit` reference, and `audit` is a
  near-identical twin of `process`.  A control-arm agent can diff the two
  functions to find a drift in `process`; that is a free oracle and a
  confound.  The next iteration should use a single-function reference or
  make the twin legitimately different.
