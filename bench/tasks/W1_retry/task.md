# Task W1: retry decorator (write from scratch)

Implement `retry` in `solution.py`.

```python
def retry(attempts=3, base_delay=0.1, exceptions=(Exception,), sleep=time.sleep):
    ...
```

`retry(...)` returns a decorator. The decorated function:

- is called at most `attempts` times;
- if it raises an exception that is an instance of one of `exceptions`, sleeps
  `base_delay * (2 ** attempt)` seconds plus a jitter in `[0, 0.1 * delay]`,
  then retries;
- if all attempts fail, re-raises the last exception;
- lets exceptions not in `exceptions` propagate immediately;
- preserves `__name__` and `__doc__` via `functools.wraps`;
- uses the provided `sleep` callable (so tests can inject a fake).

`attempt` is 0-based. `attempts=1` means one call and no sleep.

Use only the Python standard library. The public tests are in
`tests_public.py`; hidden tests exercise the same contract more thoroughly.
