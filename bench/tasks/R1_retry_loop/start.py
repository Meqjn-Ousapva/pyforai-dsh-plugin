"""The code to refactor for task R1."""

from __future__ import annotations

import time


class FlakyClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self):
        self.calls += 1
        if self.calls < 3:
            raise ConnectionError("temporary")
        return {"ok": True, "calls": self.calls}


def fetch_with_retry(client, attempts=3, delay=0.0, sleep=time.sleep):
    result = None
    for attempt in range(attempts):
        result = client.fetch()
        break
    return result
