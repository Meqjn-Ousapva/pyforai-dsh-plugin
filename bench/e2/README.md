# E2: forced-reindent structural editing

E2 measures whether `pyforai wrap` reduces the cost of edits that **must**
re-indent a large block.  The task has no `else:`-reuse or other local
shortcut: wrapping the whole `for` loop moves the loop header and every body
statement one level.

## Tasks

| task | body statements | required reindent |
|---|---|---|
| `E2_wrap_020` | 26 | 27 lines |
| `E2_wrap_080` | 86 | 87 lines |
| `E2_wrap_200` | 206 | 207 lines |

Each task starts from a working `process(records)` and asks for:

```python
try:
    for record in records:
        ...
except Exception as exc:
    report["errors"].append((record.id, str(exc)))
```

## Arms

| arm | rules |
|---|---|
| `manual` | direct edits; no pyforai, no formatter, no reindent script |
| `formatter` | direct edits + black; no pyforai (not run in the 2026-11-03 pilot) |
| `plugin` | `pyforai wrap --header <line> --kind try ...`, then `check` |

## Metrics

* `solved` — public + hidden pass, target AST matches, no collateral changes.
* `target_ast` — solution AST equals the expected AST.
* `collateral` — AST outside the target `for` body changed.
* `snapshot_payload` — bytes in the per-edit snapshots (includes tool changes).
* `model_payload_proxy` — snapshot bytes for manual, command bytes for plugin;
  the best available proxy for emitted output.
* `first_edit_s`, `wall_time_s`, `check_calls`.

## Run

```bash
python -m bench.e2.run build --sizes 20,80,200
python -m bench.e2.run init --arms manual,plugin
python -m bench.e2.run score
python -m bench.e2.run report
```

Results: [`FINDINGS.md`](FINDINGS.md) and [`results/report.md`](results/report.md).

## Status

Pilot complete.  All six runs solved with target AST and no collateral.  The
plugin's model-side payload is ~27x smaller at 200 statements, but wall time
does not improve.  Next: real-code 200-line case, `move`/`replace-body`, native
plugin tool, actual token accounting, and the formatter arm once black is
available.
