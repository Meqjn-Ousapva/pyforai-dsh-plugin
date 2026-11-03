"""Hidden tests for task R1 (retry loop refactor)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from solution import FlakyClient, fetch_with_retry


class FetchRetryHiddenTests(unittest.TestCase):
    def test_attempts_one_no_sleep(self) -> None:
        calls: list[int] = []
        delays: list[float] = []

        class AlwaysFails:
            def fetch(self):
                calls.append(1)
                raise ConnectionError("x")

        with self.assertRaises(ConnectionError):
            fetch_with_retry(AlwaysFails(), attempts=1, delay=0.5, sleep=delays.append)
        self.assertEqual(len(calls), 1)
        self.assertEqual(delays, [])

    def test_success_first_try_no_sleep(self) -> None:
        delays: list[float] = []

        class Works:
            def fetch(self):
                return "ok"

        self.assertEqual(
            fetch_with_retry(Works(), attempts=3, delay=0.5, sleep=delays.append),
            "ok",
        )
        self.assertEqual(delays, [])

    def test_sleep_delay_value(self) -> None:
        delays: list[float] = []

        class FailsTwice:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self):
                self.calls += 1
                if self.calls < 3:
                    raise ConnectionError("x")
                return 1

        fetch_with_retry(FailsTwice(), attempts=3, delay=0.125, sleep=delays.append)
        self.assertEqual(delays, [0.125, 0.125])

    def test_preserves_client(self) -> None:
        client = FlakyClient()
        fetch_with_retry(client, attempts=3, delay=0.0, sleep=lambda s: None)
        self.assertEqual(client.calls, 3)


if __name__ == "__main__":
    unittest.main()
