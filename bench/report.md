# Pilot results

Generated: 2026-11-03 11:49:28

> **This is a pilot with one run per task×arm cell.** It is a smoke test of the
> measurement pipeline and a source of effect-size hints, not a powered study.
> Do not read p-values or confidence intervals into these numbers.

## Per run

| task | arm | public | hidden | anchor err | anchors | LOC | diff +/- | repair | wall s | pyforai ops+help | flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1_retry_loop | A | yes | yes | 0 | 0 | 21 | 9/4 | 0 | 10 | 0+0 |  |
| R1_retry_loop | B | yes | yes | 0 | 4 | 24 | 11/4 | 0 | 60 | 1+0 |  |
| R1_retry_loop | C | yes | yes | 0 | 8 | 28 | 15/4 | 0 | 58 | 6+6 |  |
| R2_reconcile | A | yes | yes | 0 | 0 | 37 | 10/7 | 0 | 6 | —+— |  |
| R2_reconcile | B | yes | yes | 0 | 6 | 43 | 16/7 | 0 | 81 | 3+3 |  |
| R2_reconcile | C | yes | yes | 0 | 1 | 38 | 11/7 | 0 | 16 | 2+0 |  |
| W1_retry | A | yes | yes | 0 | 0 | 31 | 39/0 | 0 | 16 | 0+0 |  |
| W1_retry | B | yes | yes | 0 | 6 | 62 | 70/0 | 0 | 74 | 2+0 |  |
| W1_retry | C | yes | yes | 0 | 8 | 45 | 55/0 | 0 | 57 | 4+0 |  |

## Aggregate by arm

| arm | condition | n | public | hidden | anchor err | anchors | LOC | diff | repair | wall s | success/min | pyforai ops+help | tampered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | no anchors | 3 | 3/3 | 3/3 | 0.0 | 0.0 | 29.7 | 23.0 | 0.0 | 10.7 | 5.62 | 0.0+0.0 | 0 |
| B | anchors | 3 | 3/3 | 3/3 | 0.0 | 5.3 | 43.0 | 36.0 | 0.0 | 71.7 | 0.84 | 2.0+1.0 | 0 |
| C | anchors + structural editing | 3 | 3/3 | 3/3 | 0.0 | 5.7 | 37.0 | 30.7 | 0.0 | 43.7 | 1.37 | 4.0+2.0 | 0 |

`success/min` is `hidden passes / total wall-clock minutes` for runs that
reported `started_at.txt` and `finished_at.txt`. `diff +/-` is added/removed
lines against `start.py` (for write tasks, against an empty file).
`anchor err` is the number of `pyforai check` errors in the final artifact.
`pyforai ops+help` separates actual CLI operations from `--help` discovery
calls. The latter are an onboarding cost of using a CLI without a native tool
schema; they are cheap in wall time but inflate the call count.

## Caveats

- N=1 per cell; task difficulty and model stochasticity dominate.
- Runs share the same underlying model; only the workflow instructions/tools differ.
- `wall s` and `repair` are self-reported by the agent through timestamp/log files.
- Hidden tests are copied into the run directory only after the agent finishes.
- A tampered `tests_public.py` is flagged but not automatically excluded.
