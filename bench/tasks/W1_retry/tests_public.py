"""Public tests for task W1 (retry decorator)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from solution import retry


class RetryPublicTests(unittest.TestCase):
    def test_success_first_try(self) -> None:
        delays: list[float] = []

        @retry(attempts=3, sleep=delays.append)
        def f():
            return 42

        self.assertEqual(f(), 42)
        self.assertEqual(delays, [])

    def test_retries_until_success(self) -> None:
        calls: list[int] = []
        delays: list[float] = []

        @retry(attempts=3, base_delay=0.5, sleep=delays.append)
        def f():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("boom")
            return "ok"

        self.assertEqual(f(), "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(delays), 2)

    def test_gives_up(self) -> None:
        @retry(attempts=2, sleep=lambda s: None)
        def f():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            f()

    def test_non_listed_exception_propagates(self) -> None:
        @retry(attempts=3, exceptions=(ValueError,), sleep=lambda s: None)
        def f():
            raise TypeError("nope")

        with self.assertRaises(TypeError):
            f()

    def test_metadata(self) -> None:
        @retry()
        def f():
            """doc"""

        self.assertEqual(f.__name__, "f")
        self.assertEqual(f.__doc__, "doc")


if __name__ == "__main__":
    unittest.main()
