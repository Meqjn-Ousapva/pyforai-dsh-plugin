# E1: verification, not end-to-end task success

E1 asks one question:

> **When a Python edit silently changes block structure, does `pyforai check`
> catch it, and does having `check` help an agent repair it?**

It does **not** try to answer "does pyforai make agents better at programming".
That is E2 (structural editing) and E3 (real PR tasks).  E1 is deliberately
small, deterministic where possible, and cheap enough to run on every change.

**Read [`FINDINGS.md`](FINDINGS.md) for the 2026-11-03 results** — including
the two `fmt`/strict defects, the `black` laundering path, and the repair-pilot
ceiling.

## Two components

### 1. Deterministic drift suite (`drift/`)

We take 20 real Python files (12 from CPython 3.12, 8 from this repository),
pick a few blocks per file, insert one anchor, and inject one syntax-valid
structural drift.  The file still parses; `py_compile` is happy.  Then we
compare:

* `py_compile` — expected to miss every case,
* `pyforai check` — does it report an error, and which code,
* `pyforai check --strict` — does it catch the deleted-anchor case (E010).

Drift classes fall into three groups:

| group | examples | what it tests |
|---|---|---|
| anchor moved/edited | kind mismatch (E001), wrong column (E002), inside block (E003), duplicate (E005), code before anchor (E007), outer before inner (E008) | the checker's basic invariants |
| code moved, anchor fixed | last statement dedented out of a block (E004), sibling inserted before the anchor (E004) | the realistic "edit changed structure" case |
| coverage / limitation | anchor deleted (E010 only under `--strict`), anchor moved with the code (undetectable) | strict-mode policy and the checker's known blind spot |

The suite also records:

* **false positives** on clean anchored files,
* **`fmt` robustness** on every corpus file (does `fmt` exit 0, is the result
  clean, is a second `fmt` idempotent),
* **black interaction**: does `black` preserve the drift, fix it, or mask it?
  `black` re-indenting a misplaced anchor is a real laundering path: the code
  is still wrong, but `check` after `black` may be clean.

Run:

The black-interaction check needs `black`; install it locally if missing:

```bash
python -m pip install --target bench/e1/.deps -r bench/e1/requirements.txt
```

Then:

```bash
cd python-for-AI
python -m bench.e1.run_drift --quick      # 6 files, smoke test
python -m bench.e1.run_drift              # 20 files, with black
python -m bench.e1.run_drift --formatter none
```

Results: `bench/e1/drift/results/report.md`, `summary.json`, `cases.jsonl`.
Each generated case is written to `results/cases/` for inspection; that directory is regenerated on each run and is not kept in the cleaned tree.

The corpus is vendored under `corpus/files/` with a manifest, so a result does
not depend on the host interpreter's standard library.  Verify it with:

```bash
python -m bench.e1.corpus verify
```

### 2. Repair tasks (`repair/`)

The deterministic suite shows the checker *can* see a drift.  The repair tasks
ask whether an agent *uses* it.

Construction starts from a known-correct solution (the `T*_pipeline`
references vendored under `repair/sources/reference/`).  We inject
`dedent_last` or `hoist_else`, keep the case only if

* the file still parses,
* `pyforai check` reports a structural error,
* the public tests fail (the agent has a signal), and
* the hidden tests fail (the case is not already solved).

Two arms:

| arm | prompt | expected behaviour |
|---|---|---|
| `check_on` | run `pyforai check solution.py` before and after editing | use the diagnostic to locate the line |
| `check_off` | do not use `pyforai`; debug from tests and code | manual localisation |

Both arms see the same anchors and tests.  The anchors are assertions; the
prompt says not to edit them, and the score records whether they changed.

```bash
python -m bench.e1.repair build --tasks T1_pipeline,T4_pipeline,T8_pipeline
python -m bench.e1.repair init --arms check_on,check_off --reps 1
python -m bench.e1.repair score
python -m bench.e1.repair report
```

Results: `bench/e1/repair/results/report.md`.

Primary outcome:

* `solved` = public + hidden pass, **no anchor edited**, and final `check` clean.
* `behavior_only` = public + hidden pass, ignoring the anchor constraint.
* `anchors_modified` = position-independent fingerprint of every `# end` line
  changed.
* `laundered` = anchors changed and final `check` is clean: the agent made the
  checker agree by editing the assertion instead of the code.
* `edit_payload_bytes` = sum of added/removed bytes across per-edit snapshots;
  a proxy for output tokens, not a token count.

## Layout

```
bench/e1/
├── README.md
├── FINDINGS.md                # 2026-11-03 results + decision implications
├── common.py                  # hashing, check wrappers, diff/snapshot helpers
├── corpus.py                  # manifest + verify
├── drift.py                   # injection library (targets, drift classes)
├── run_drift.py               # deterministic suite
├── repair.py                  # build / init / score / report for repair tasks
├── requirements.txt           # optional black for formatter checks
├── corpus/
│   ├── MANIFEST.json
│   ├── NOTICE.md
│   └── files/                 # 20 vendored real files
├── drift/results/             # generated report + archived case data
└── repair/
    ├── sources/               # vendored T tasks / hidden / reference
    ├── tasks/                 # generated repair tasks
    ├── runs/                  # generated run directories
    └── results/               # generated report + archived metrics
```

## Method notes

* **One anchor per case.**  The drift suite isolates the checker's decision: it
  does not test interactions between many anchors.  That is deliberate; the
  E2 editing suite will cover multi-anchor files.
* **`py_compile` is the control.**  Every case is syntax-valid by construction.
  The control's detection rate is 0%, which is the point: a test-free syntax
  check cannot see block ownership.
* **`fmt` output is derived.**  `fmt` inserts anchors from the AST, so a
  `fmt` → `check` sequence is tautological.  E1 treats `fmt` as a formatter
  robustness test, not as evidence that the code is correct.
* **`check_off` is prompt-level.**  There is no sandbox that removes the CLI.
  The score records whether the arm actually called it.  A future version should
  run each arm in a container with a restricted PATH.
* **The measured binary is the product binary.**  `common.py` prefers
  `pyforai` on `PATH` (the Go 0.2.0 build the plugin ships); set `PYFORAI_BIN`
  to override.  The Python reference is used to generate cases and as a
  cross-check; on the 2026-11-03 corpus the two agreed on every case.
* **Line accuracy matters.**  A diagnostic that points at the anchor line is
  useful; one that points 100 lines away is not.  The suite records the mean
  distance between the first error and the injected drift.

## What E1 does not answer

* Whether `wrap` / `move` / `replace-body` reduce reindentation work or diff
  noise.  That is E2: forced-reindent tasks, output-token and collateral-change
  metrics.
* Whether any of this improves real PR work.  That is E3, and it only makes
  sense if E2 shows a signal.
* Whether anchors improve *generation*.  The pilot already suggested the effect
  is small; E1 does not re-test it.
