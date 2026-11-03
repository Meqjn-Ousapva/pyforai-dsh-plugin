# Repair task: T8_pipeline

`solution.py` is a working solution to the original `T8_pipeline` refactor task.
A previous edit introduced a **structural drift**: the code still parses, but a
statement now belongs to a different block than intended. The `# end ...`
anchors in the file describe the intended block structure from before the edit.

The public tests **pass**, but the hidden tests fail.  The drift is in a branch the public examples do not exercise.  Use the anchors and `check` (in the check_on arm) to locate it; do not assume that a green public suite means the file is correct.

Your job is to restore the intended behaviour.

Rules:

- Edit `solution.py` in place.
- Do **not** modify `task.md` or `tests_public.py`.
- Do **not** modify, add, or remove any `# end ...` anchor. They are assertions,
  not decoration. If the anchors and the code disagree, fix the code.
- At most 3 repair attempts (a repair attempt is a test run that fails).
- The structural drift is local. Do not rewrite the whole function.
