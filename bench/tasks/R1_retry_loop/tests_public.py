"""Public tests for task R1 (retry loop refactor)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from solution import FlakyClient, fetch_with_retry


class FetchRetryPublicTests(unittest.TestCase):
    def test_succeeds_on_third_call(self) -> None:
        client = FlakyClient()
        result = fetch_with_retry(client, attempts=3, delay=0.0, sleep=lambda s: None)
        self.assertEqual(result, {"ok": True, "calls": 3})

    def test_raises_after_attempts(self) -> None:
        class AlwaysFails:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self):
                self.calls += 1
                raise ConnectionError("no")

        client = AlwaysFails()
        with self.assertRaises(ConnectionError):
            fetch_with_retry(client, attempts=3, delay=0.0, sleep=lambda s: None)
        self.assertEqual(client.calls, 3)

    def test_sleeps_between_attempts(self) -> None:
        delays: list[float] = []
        client = FlakyClient()
        fetch_with_retry(client, attempts=3, delay=0.25, sleep=delays.append)
        self.assertEqual(delays, [0.25, 0.25])

    def test_non_connection_error_propagates(self) -> None:
        class Boom:
            def fetch(self):
                raise ValueError("nope")

        with self.assertRaises(ValueError):
            fetch_with_retry(Boom(), attempts=3, delay=0.0, sleep=lambda s: None)


if __name__ == "__main__":
    unittest.main()
