# Arm C — anchors + structural editing

- Write plain, idiomatic Python.
- Use the `pyforai` CLI for structural changes instead of re-indenting blocks by
  hand:

  ```bash
  python -m pyforai replace-body {run}/solution.py --header N --code-file {run}/body.py
  python -m pyforai wrap {run}/solution.py --header N --kind try --except "Exception as exc" --handler "..."
  python -m pyforai move {run}/solution.py --header N --before-line M
  ```

- After each structural edit, run:

  ```bash
  python -m pyforai check {run}/solution.py
  ```

  and fix every anchor error.
- For code you wrote from scratch, run once:

  ```bash
  python -m pyforai fmt --min-lines 5 --min-depth 3 {run}/solution.py
  python -m pyforai check {run}/solution.py
  ```

  Do not use `--all`; it anchors every block and defeats the sparse policy.

- Prefer a tool-driven edit whenever you would otherwise re-indent a block.
  If `replace-body` is not applicable, a direct edit is still allowed.
