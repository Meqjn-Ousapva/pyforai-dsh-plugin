"""E1: does the anchor checker catch structural drift, and does it help repair it?

The old three-arm bench measured end-to-end task success.  E1 measures the
*verification mechanism* directly:

* ``drift``  -- deterministic injection of syntax-valid structural drift into
  real Python files.  Compare ``py_compile`` with ``pyforai check``.
* ``repair`` -- LLM tasks where a drifted file must be restored.  Compare
  check-on and check-off arms.

See ``bench/e1/README.md``.
"""

__all__ = []
