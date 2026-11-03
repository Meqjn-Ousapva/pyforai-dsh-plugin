# E1.1: single-function repair, no twin oracle

**Results: [FINDINGS.md](FINDINGS.md).**  The pilot is still at a ceiling; see
the findings for why the single-anchor task is too easy and what E1.2 needs.

E1.1 follows E1's repair pilot.  The pilot hit a ceiling because the T-family
reference has two near-identical functions (`process` and `audit`), so a
control agent could diff the twin to localise a drift.  E1.1 removes the twin:

* the source is a single `process` function with 32 record kinds;
* the drift is **silent**: the public tests pass, the hidden tests fail;
* the drift is in a branch the public examples do not exercise.

## Arms

| arm | how the diagnostic arrives |
|---|---|
| `no_check` | not at all; debug from tests, anchors, and code |
| `tool_check` | the agent runs `pyforai check` itself |
| `forced_diagnostic` | the harness runs `pyforai check` on the start file and writes `diagnostics.md`; the agent reads it first |

The `forced_diagnostic` arm separates the **value of the diagnostic** from the
model's ability to invoke the tool.  This matters most for a weak model.

## Build and run

```bash
python -m bench.e1.e11.run build --tasks 4
python -m bench.e1.e11.run init --arms no_check,tool_check,forced_diagnostic
python -m bench.e1.e11.run score
python -m bench.e1.e11.run report
```

Results: `bench/e1/e11/results/report.md`.

## Metrics

* `solved` — public + hidden pass, no anchor edited, final `check` clean.
* `first_try` — solved with no failed test run.
* `time_to_first_edit_s` — first `edits/` snapshot timestamp minus
  `started_at.txt`.
* `wall_time_s` — `finished_at.txt - started_at.txt`.
* `edit_payload_bytes` — added/removed bytes across snapshots; a proxy for
  output tokens, not a token count.
* `check_calls`, `anchors_modified`, `arm_compliance`.

Token usage is recorded only if the runner writes `usage.json`; DSH subagents do
not expose it, so the pilot relies on the payload/time proxies.

## Source

`repair/sources`-style provenance is in `e11/sources/`:
`reference.py` (single `process`), `tests_public.py`, `hidden.py`.  The
generated tasks live in `e11/tasks/`; runs are disposable.
