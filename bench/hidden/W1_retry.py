"""Hidden tests for task W1 (retry decorator)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from solution import retry


class RetryHiddenTests(unittest.TestCase):
    def test_attempts_one_no_sleep(self) -> None:
        calls: list[int] = []
        delays: list[float] = []

        @retry(attempts=1, sleep=delays.append)
        def f():
            calls.append(1)
            raise ValueError("x")

        with self.assertRaises(ValueError):
            f()
        self.assertEqual(len(calls), 1)
        self.assertEqual(delays, [])

    def test_delay_growth_and_jitter_bounds(self) -> None:
        delays: list[float] = []

        @retry(attempts=3, base_delay=0.1, sleep=delays.append)
        def f():
            raise ValueError("x")

        with self.assertRaises(ValueError):
            f()
        self.assertEqual(len(delays), 2)
        self.assertGreaterEqual(delays[0], 0.1)
        self.assertLessEqual(delays[0], 0.11 + 1e-12)
        self.assertGreaterEqual(delays[1], 0.2)
        self.assertLessEqual(delays[1], 0.22 + 1e-12)

    def test_forwards_arguments(self) -> None:
        @retry(attempts=1, sleep=lambda s: None)
        def f(a, b=2):
            return a + b

        self.assertEqual(f(1, b=3), 4)

    def test_does_not_sleep_after_success(self) -> None:
        delays: list[float] = []

        @retry(attempts=3, sleep=delays.append)
        def f():
            return 1

        f()
        self.assertEqual(delays, [])


if __name__ == "__main__":
    unittest.main()
