"""Anchors on the blocks that carry real structure (default check passes)."""

from __future__ import annotations


def total_positive(values: list[int]) -> int:
    total = 0
    for value in values:
        if value > 0:
            total += value
        # end if
    # end for
    return total


class Retry:
    def __init__(self, attempts: int = 3) -> None:
        self.attempts = attempts

    def run(self, fn):
        last: Exception | None = None
        for _ in range(self.attempts):
            try:
                return fn()
            except Exception as exc:
                last = exc
            # end try
        # end for
        raise last if last is not None else RuntimeError("no attempts")
