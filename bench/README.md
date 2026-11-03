# Bench

Three self-contained benchmarks under `bench/`:

| part | question | status |
|---|---|---|
| [`e1/`](e1/README.md) | does `pyforai check` catch structural drift, and does it help repair it? | complete |
| [`e1/e11/`](e1/e11/README.md) | same, but single-function / no twin / silent drift | pilot complete; on hold |
| [`e2/`](e2/README.md) | does `pyforai wrap` reduce the cost of a forced re-indent? | pilot complete |

All three share the same shape: the harness prepares run directories and
scores artifacts; an external agent produces the artifact.  The harness never
calls an LLM.

**Data-backed summary of what the plugin is and is not good at:
[`SUMMARY.md`](SUMMARY.md).**

## Quick start

```bash
cd python-for-AI

# E1: deterministic drift detection + repair pilot
python -m bench.e1.run_drift --quick
python -m bench.e1.run_drift
python -m bench.e1.repair build --tasks T1_pipeline,T4_pipeline,T8_pipeline
python -m bench.e1.repair init --arms check_on,check_off --reps 1
python -m bench.e1.repair score
python -m bench.e1.repair report

# E1.1: single-function silent drift, three diagnostic arms
python -m bench.e1.e11.run build --tasks 4
python -m bench.e1.e11.run init --arms no_check,tool_check,forced_diagnostic
python -m bench.e1.e11.run score
python -m bench.e1.e11.run report

# E2: forced-reindent structural editing
python -m bench.e2.run build --sizes 20,80,200
python -m bench.e2.run init --arms manual,plugin
python -m bench.e2.run score
python -m bench.e2.run report
```

Generated `runs/` and `cases/` directories are disposable; reports and
aggregate metrics are retained under each part's `results/`.

## What each part measures

### E1: verification

- **Detection:** syntax-valid structural drift injected into 20 real files;
  compare `py_compile` with `pyforai check`; false positives on clean anchored
  files; strict-mode coverage.
- **Formatter interaction:** `fmt` robustness and whether `black` can mask a
  drift (it can, for a misplaced anchor).
- **Repair:** `check_on` vs `check_off` on visible and silent drifts.

### E1.1: no-twin repair

E1's repair pilot had a free oracle: `process` and `audit` were near-identical.
E1.1 removes the twin, uses a single 32-kind `process`, and makes the drift
silent (public tests green, hidden tests red).  It compares three ways of
getting the diagnostic: none, the agent calls `check`, or the harness writes
the check output to `diagnostics.md` up front.

### E2: forced-reindent editing

Wrap a 20/80/200-statement `for` loop in `try/except`.  There is no `else:`
reuse shortcut: the loop header and every body statement must move one level.
Arms are `manual` (direct edits) and `plugin` (`pyforai wrap` + `check`).
Metrics separate `snapshot_payload` (includes tool changes) from a
`model_payload_proxy` (command bytes for tool runs, snapshot bytes for manual
runs), because the file diff is not the model's output.

## Results

- [`SUMMARY.md`](SUMMARY.md) — consolidated plugin advantages/limits with data.
- [`e1/FINDINGS.md`](e1/FINDINGS.md) — E1 summary and decision implications.
- [`e1/drift/results/report.md`](e1/drift/results/report.md) — detection,
  formatter, black.
- [`e1/repair/results/report.md`](e1/repair/results/report.md) — repair pilot.
- [`e1/e11/FINDINGS.md`](e1/e11/FINDINGS.md) — no-twin pilot; still a ceiling.
- [`e1/e11/results/report.md`](e1/e11/results/report.md) — per-run and aggregate.
- [`e2/FINDINGS.md`](e2/FINDINGS.md) — forced-reindent pilot: output economy
  without a wall-time gain.
- [`e2/results/report.md`](e2/results/report.md) — per-run and aggregate.

Headline results:

- `check` catches the drift classes we can generate with no false positives on
  clean anchored files; the repair pilots are still at a ceiling for a strong
  model.
- `fmt` inserts derived anchors, so `fmt` → `check` is self-confirming; `black`
  can re-align a misplaced anchor and hide the drift.
- On the 200-statement wrap, the plugin's model-side payload proxy is ~27×
  smaller than manual, but wall time does not improve.  The case for the tool
  is output/token cost, not latency.

## Layout

```
bench/
├── README.md
├── e1/
│   ├── README.md, FINDINGS.md
│   ├── common.py, corpus.py, drift.py, run_drift.py, repair.py
│   ├── corpus/                 # 20 vendored real files + manifest
│   ├── drift/results/          # detection report + archived case data
│   ├── repair/                 # sources/, tasks/, results/
│   └── e11/                    # single-function repair pilot
└── e2/
    ├── README.md, FINDINGS.md
    ├── run.py                  # build / init / score / report
    ├── tasks/                  # 20/80/200-statement wrap tasks
    └── results/                # per-run + aggregate report
```

## Optional formatter

`black` is only needed for the formatter-interaction part of E1 and the optional
`formatter` arm of E2.  It is not installed by default:

```bash
python -m pip install --target bench/e1/.deps -r bench/e1/requirements.txt
```

For E2's formatter arm, use a `black` on `PATH` and
`init --arms manual,formatter,plugin`; the pilot ran only `manual` and
`plugin`.

## Roadmap

| stage | question | status |
|---|---|---|
| E1 | does `check` catch drift, and does it help repair? | complete |
| E1.1 | no-twin, silent drift, diagnostic delivery | pilot complete; on hold |
| E2 | does `wrap` reduce forced-reindent cost? | pilot complete; needs real code, `move` / `replace-body`, and token accounting |
| E3 | does it help on real PR refactors? | only after E2 shows a signal on the cost metric that matters |

The old three-arm A/B/C pilot was removed.  Its useful conclusions are
reflected in E1/E1.1 (verification) and E2 (editing); there is no separate
`ANALYZE.md`.
