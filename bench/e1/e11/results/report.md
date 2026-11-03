# E1.1 repair report

Generated: 2026-11-03 15:42:59

> Small pilot.  Single-function source (no `audit` twin), silent drift,
> public tests green / hidden tests red.  N is small; treat differences as
> hypotheses.

## Per run

| task | arm | solved | first try | first edit s | wall s | payload B | check calls | anchors moved | compliance |
|---|---|---|---|---|---|---|---|---|---|
| E11_01_L53 | forced_diagnostic | yes | yes | 50 | 60 | 134 | 0 | no | yes |
| E11_01_L53 | no_check | yes | yes | 20 | 39 | 134 | 0 | no | yes |
| E11_01_L53 | tool_check | yes | yes | 10 | 21 | 134 | 2 | no | yes |
| E11_02_L58 | forced_diagnostic | yes | yes | 11 | 23 | 202 | 0 | no | yes |
| E11_02_L58 | no_check | yes | yes | 15 | 27 | 202 | 0 | no | yes |
| E11_02_L58 | tool_check | yes | yes | 10 | 20 | 202 | 2 | no | yes |
| E11_03_L63 | forced_diagnostic | yes | yes | 5 | 13 | 202 | 0 | no | yes |
| E11_03_L63 | no_check | yes | yes | 15 | 32 | 202 | 0 | no | yes |
| E11_03_L63 | tool_check | yes | yes | 15 | 29 | 202 | 3 | no | yes |
| E11_04_L68 | forced_diagnostic | yes | yes | 6 | 17 | 134 | 0 | no | yes |
| E11_04_L68 | no_check | yes | yes | 12 | 24 | 134 | 0 | no | yes |
| E11_04_L68 | tool_check | yes | yes | 12 | 32 | 134 | 2 | no | yes |

## Aggregate

| arm | n | solved | first try | mean first edit s | mean wall s | mean payload B | check used | anchors moved |
|---|---|---|---|---|---|---|---|---|
| no_check | 4 | 4/4 | 4/4 | 15.5 | 30.5 | 168.0 | 0/4 | 0 |
| tool_check | 4 | 4/4 | 4/4 | 11.8 | 25.5 | 168.0 | 4/4 | 0 |
| forced_diagnostic | 4 | 4/4 | 4/4 | 18.0 | 28.2 | 168.0 | 0/4 | 0 |

``first try`` = solved with no failed test run.
``first edit s`` = first snapshot timestamp minus `started_at.txt`.
``payload B`` = added/removed bytes across per-edit snapshots; a proxy for
output tokens, not a token count.

## Caveats

- Token usage is not available from the runner; `payload B` and wall time are
  proxies.
- `forced_diagnostic` gets the check output for free; `tool_check` must invoke
  the tool.  The difference is diagnostic delivery, not just model ability.
- `no_check` compliance is prompt-level.
