# E2 task: wrap a 200-statement loop

`solution.py` contains a working `process(records)` function with a
`for record in records:` loop (header at line 13).

Wrap the **entire `for` loop** in:

```python
try:
    for record in records:
        ...
except Exception as exc:
    report["errors"].append((record.id, str(exc)))
```

Behaviour:

- a failing record raises; append `(record.id, str(exc))` to
  `report["errors"]` and stop processing further records;
- successful and skipped records before the failure keep their behaviour;
- do not add new top-level functions, classes, or methods;
- keep `Record` and the `process` signature.

The public tests are in `tests_public.py`.  Edit `solution.py` in place.
