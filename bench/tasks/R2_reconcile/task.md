# Task R2: per-account error isolation (larger structural refactor)

`solution.py` contains a working `reconcile` function. It iterates over accounts,
and for each active account iterates over its ledger entries, updating a report.

Refactor `reconcile` so that the per-account processing is isolated:

- Wrap the body of `if account.active:` in a `try/except Exception as exc`.
- If `ledger.get(...)` or any processing for one account raises, append
  `(account.id, "account", str(exc))` to `report["errors"]` and continue with
  the next account. One bad account must not abort the rest.
- Keep the `else` branch for inactive accounts outside the new `try`.
- Preserve the existing behavior for accounts that do not fail.
- Do not change `Account`, `Entry`, or `Ledger`.
- The signature of `reconcile` is unchanged.

`tests_public.py` contains the public tests. Edit `solution.py` in place.
