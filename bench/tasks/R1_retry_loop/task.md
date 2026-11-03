# Task R1: add retry handling to an existing loop (structural refactor)

`solution.py` contains a working `FlakyClient` and a `fetch_with_retry`
function. The function currently calls `client.fetch()` once inside a loop and
returns the result.

Refactor `fetch_with_retry` so that:

- a `ConnectionError` raised by `client.fetch()` is caught, and the call is
  retried up to `attempts` times in total;
- between attempts it calls `sleep(delay)` exactly once per failed attempt;
- if all attempts fail, it re-raises the last `ConnectionError`;
- a successful return value is returned unchanged;
- exceptions that are not `ConnectionError` propagate immediately;
- the public signature `fetch_with_retry(client, attempts=3, delay=0.0, sleep=time.sleep)`
  is preserved;
- `FlakyClient` is not modified.

`tests_public.py` contains the public tests. Edit `solution.py` in place.
