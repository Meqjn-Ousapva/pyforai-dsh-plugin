# E1.1 repair task 01: single-function silent drift

`solution.py` is a working single-function module.  A previous edit introduced a
**structural drift** in one branch: the code still parses, the public tests
still pass, but the hidden tests fail.

The `# end ...` anchors describe the intended block structure from before the
edit.  They are assertions, not decoration.

Your job is to restore the intended behaviour.

Rules:

- Edit `solution.py` in place.
- Do **not** modify `task.md` or `tests_public.py`.
- Do **not** modify, add, or remove any `# end ...` anchor.
- At most 3 repair attempts (a repair attempt is a test run that fails).
- The drift is local.  Do not rewrite the whole function.
