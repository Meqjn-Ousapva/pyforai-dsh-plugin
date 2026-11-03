# Task T6_pipeline: two-function structural refactor (24 kinds)

`solution.py` contains a working `process(records, backend, notifier=None)` and
`audit(records, backend)`. Refactor both in place:

1. In `process`, if `records` is empty, call `notifier(report)` once if
   provided, increment `report["notified"]`, and return `report`.
2. In `process`, wrap the per-record processing in `try/except Exception as
   exc`. On failure append `(record.id, "record", str(exc))` to
   `report["errors"]` and continue with the next record.
3. In `process`, call `notifier(report)` exactly once at the end, not once per
   record, and increment `report["notified"]` by 1. If no notifier is provided,
   leave it 0.
4. In `audit`, wrap the per-record processing in `try/except Exception as exc`.
   On failure append `(record.id, "audit", str(exc))` to `report["errors"]` and
   continue with the next record.
5. Preserve all existing branch behavior in both functions, and keep the
   `Record`, `Entry`, `Backend` classes and both signatures.
6. Do not add new top-level functions, methods, classes, or lambdas. Keep the
   refactor inside `process` and `audit`; `tests_public.py` checks this.

The public tests are in `tests_public.py`. Edit `solution.py` in place.
