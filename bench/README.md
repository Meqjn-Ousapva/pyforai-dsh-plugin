# Bench

The bench is **[`e1/`](e1/README.md)**: a verification-focused measurement of
whether `pyforai check` catches structural drift, and whether having `check`
helps an agent repair a drifted file.

E1 is self-contained: its 20-file corpus, T-family repair sources, generated
repair tasks, and result reports all live under `e1/`.  The old three-arm
A/B/C pilot (`harness.py`, `runs/`, `arms/`, `tasks/`, `hidden/`,
`calibrate/`, `DESIGN.md`, `PILOT.md`, `report.*`) has been removed; its
conclusions are summarized in [`ANALYZE.md`](ANALYZE.md) and
[`e1/FINDINGS.md`](e1/FINDINGS.md).

## Quick start

```bash
cd python-for-AI

# deterministic: 20 real files, 10 drift classes, py_compile as control
python -m bench.e1.run_drift --quick
python -m bench.e1.run_drift

# behavioural: repair tasks, check_on vs check_off
python -m bench.e1.repair build --tasks T1_pipeline,T4_pipeline,T8_pipeline
python -m bench.e1.repair init --arms check_on,check_off --reps 1
python -m bench.e1.repair score
python -m bench.e1.repair report
```

Black is optional for the formatter-interaction section:

```bash
python -m pip install --target bench/e1/.deps -r bench/e1/requirements.txt
```

## What E1 measures

* **Detection:** injected syntax-valid structural drift vs `py_compile` and
  `pyforai check`; false positives on clean anchored files; strict-mode
  coverage.
* **Formatter interaction:** `fmt` robustness and whether `black` can mask a
  drift (it can, for a misplaced anchor).
* **Repair behaviour:** `check_on` vs `check_off` on visible and silent drifts;
  solved, anchors modified, laundering, check calls, per-edit payload.

E1 does **not** measure `wrap` / `move` / `replace-body` value or real-PR
success.  Those are E2 and E3; the design is in
[`ANALYZE.md`](ANALYZE.md) and [`e1/README.md`](e1/README.md).

## Results

* [`e1/FINDINGS.md`](e1/FINDINGS.md) — summary and internal-decision
  implications.
* [`e1/drift/results/report.md`](e1/drift/results/report.md) — detection,
  formatter, black.
* [`e1/repair/results/report.md`](e1/repair/results/report.md) — repair pilot.

## Roadmap

| stage | question | status |
|---|---|---|
| **E1** | does `check` catch drift, and does it help repair? | implemented; see `e1/FINDINGS.md` |
| **E2** | do `wrap` / `move` / `replace-body` reduce reindentation work and diff noise? | not started |
| **E3** | does any of it help on real PR refactors? | only after E2 shows a signal |
