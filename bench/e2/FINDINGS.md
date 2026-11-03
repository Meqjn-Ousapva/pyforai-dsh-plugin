# E2 findings (2026-11-03)

E2 asks whether structural editing (`pyforai wrap`) reduces the cost of a
**forced re-indent**.  Three tasks wrap a 20/80/200-statement `for` loop in
`try/except`; there is no `else:`-reuse or other local shortcut.  The correct
edit must move the whole loop one level.

## Result

Six runs (3 sizes x manual/plugin), strong model, one run per cell:

| size | arm | solved | target AST | collateral | snapshot B | model proxy B | first edit s | wall s |
|---|---|---|---|---|---|---|---|---|
| 20 | manual | yes | yes | no | 2060 | 2060 | 7 | 21 |
| 20 | plugin | yes | yes | no | 2075 | 408 | 16 | 29 |
| 80 | manual | yes | yes | no | 6620 | 6620 | 10 | 24 |
| 80 | plugin | yes | yes | no | 6635 | 229 | 11 | 27 |
| 200 | manual | yes | yes | no | 15940 | 15940 | 17 | 33 |
| 200 | plugin | yes | yes | no | 15955 | 251 | 16 | 34 |

Aggregate:

| arm | n | solved | target AST | mean model proxy B | mean first edit s | mean wall s |
|---|---|---|---|---|---|---|
| manual | 3 | 3/3 | 3/3 | 8206.7 | 11.3 | 26.0 |
| plugin | 3 | 3/3 | 3/3 | 296.0 | 14.3 | 30.0 |

## Reading the numbers

**The tool's value is output economy, not correctness or latency.**

* Manual output scales linearly with block size: ~2.1 KB -> 6.6 KB -> 15.9 KB.
* The plugin's model-side payload stays flat at ~0.2–0.4 KB (the command line);
  at 200 statements that is ~27x less emitted text.  The snapshot payload is
  ~16 KB for both arms because the tool's file change is captured in the same
  snapshot; that is why the report separates `snapshot B` from `model proxy B`.
* Wall time does **not** improve.  Manual is 21/24/33 s; plugin is 29/27/34 s.
  The tool call + check costs a few seconds, and the strong model is already
  fast at bulk edits.  If latency is the metric, the tool is not a win here.
* Correctness is a tie: all six runs match the expected AST, with no collateral
  changes outside the target loop.  The task is simple enough that both
  workflows succeed; E2 therefore cannot show a correctness benefit.
* Check calls: plugin ran one `check` per run, all clean.

## Caveats

* N=1 per cell.  The payload scaling is consistent across three sizes, but the
  wall-time comparison is not powered.
* `model proxy B` is a byte proxy, not tokens.  True prompt/completion tokens
  are unavailable from the DSH subagent runner.  The proxy counts the tool
  command for plugin runs and the snapshot diff for manual runs; it excludes
  reasoning tokens in both arms.
* The plugin arm used the CLI (`pyforai wrap`) with a command card, not the
  native DSH tool.  The native tool would remove shell quoting/help overhead.
* The formatter-only arm was not run: `black` was not available in the
  environment and the local install stalled.  Manual vs plugin is the core
  comparison; formatter-only would only test whether auto-formatting alone
  helps (it cannot insert the `try`).
* Only `wrap` was tested.  `move` and `replace-body` are expected to show a
  similar output-economy effect but larger for `replace-body` (delete a large
  body, write a one-liner).
* The tasks are synthetic.  The next step should repeat the 200-statement case
  on a real function and add `move` / `replace-body`.

## What this changes

The E2 hypothesis is **partially supported**: structural editing cuts the
text the model must emit on large re-indents, but it does not improve
correctness or wall time for a strong model.  The decision therefore depends on
what is scarce:

* if output tokens / context / cost are scarce, the tool has a clear case;
* if wall time or correctness is the target, this pilot shows no gain.

The next experiment should measure actual tokens, use the native plugin tool,
and include `replace-body` on a 200+ line block, where the output gap should be
even larger.
