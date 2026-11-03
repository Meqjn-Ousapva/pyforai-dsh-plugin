# E2 forced-reindent report

Generated: 2026-11-03 15:58:13

> Small pilot.  The task is to wrap a 20/80/200-statement loop body in
> `try/except`.  N is small; treat differences as hypotheses.

## Per run

| task | size | arm | solved | target | collateral | snapshot B | model proxy B | tool cmd B | first edit s | wall s | check calls |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E2_wrap_020 | 20 | manual | yes | yes | no | 2060 | 2060 | 0 | 7 | 21 | 0 |
| E2_wrap_020 | 20 | plugin | yes | yes | no | 2075 | 408 | 408 | 16 | 29 | 1 |
| E2_wrap_080 | 80 | manual | yes | yes | no | 6620 | 6620 | 0 | 10 | 24 | 0 |
| E2_wrap_080 | 80 | plugin | yes | yes | no | 6635 | 229 | 229 | 11 | 27 | 1 |
| E2_wrap_200 | 200 | manual | yes | yes | no | 15940 | 15940 | 0 | 17 | 33 | 0 |
| E2_wrap_200 | 200 | plugin | yes | yes | no | 15955 | 251 | 251 | 16 | 34 | 1 |

## Aggregate

| arm | n | solved | target ast | mean snapshot B | mean model proxy B | mean tool cmd B | mean first edit s | mean wall s |
|---|---|---|---|---|---|---|---|---|
| manual | 3 | 3/3 | 3/3 | 8206.7 | 8206.7 | 0.0 | 11.3 | 26.0 |
| plugin | 3 | 3/3 | 3/3 | 8221.7 | 296.0 | 296.0 | 14.3 | 30.0 |

``target`` = the solution AST equals the expected AST.
``collateral`` = AST outside the target `for` body changed.
``snapshot B`` = bytes in the agent's per-edit snapshots.  For a tool arm this
includes the tool's file changes, so it is *not* model output.
``model proxy B`` = snapshot bytes for manual arms, command bytes for tool
arms.  It is the best available proxy for emitted output; true token counts
are unavailable from the runner.  ``tool cmd B`` is the byte length of
pyforai/black command lines.
