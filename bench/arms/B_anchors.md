# Arm B — anchors, no structural editing

- Write plain, idiomatic Python.
- After each nontrivial block (body roughly 5+ lines, or nesting depth 3+),
  add a `# end <kind>` anchor aligned with the block header. Example:

  ```python
  for x in xs:
      if x:
          use(x)
      # end if
  # end for
  ```

- Before finishing, run:

  ```bash
  python -m pyforai check {run}/solution.py
  ```

  and fix every anchor error.
- Do **not** use `pyforai wrap`, `pyforai replace-body`, `pyforai move`, or
  `pyforai fmt`. Anchors are written by hand.
