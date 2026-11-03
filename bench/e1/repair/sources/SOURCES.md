# Vendored repair sources

The repair builder used to read the T-family task files from the old
`bench/tasks`, `bench/hidden`, and `bench/calibrate/_reference` directories.
Those directories are removed in the E1 cleanup, so the sources are vendored
here:

- `tasks/T*_pipeline/` — `task.md`, `start.py`, `tests_public.py`
- `hidden/T*_pipeline.py` — hidden differential tests
- `reference/T*_pipeline.py` — known-correct reference solutions
- `generate_t.py` — the original generator, kept for provenance; it still
  writes to the old `bench/tasks` paths and is not used by E1.

`bench/e1/repair.py` reads only this directory.  The generated repair tasks
live in `bench/e1/repair/tasks/`; run directories are disposable.
