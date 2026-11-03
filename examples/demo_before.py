"""A clean file with no anchors, used to demo ``fmt`` and ``wrap``."""


def process(items):
    results = []
    for item in items:
        if item.enabled:
            results.append(item.value)
    return results
