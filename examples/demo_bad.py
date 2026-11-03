"""Deliberately broken anchors for ``pyforai check``.

The file is valid Python; only the anchor *claims* are wrong.  That is exactly
the class of failure indentation cannot report by itself.
"""


def kind_mismatch(values: list[int]) -> int:
    total = 0
    for value in values:
        if value > 0:
            total += value
    # end if
    return total


def anchor_inside_block(flag: bool) -> int:
    if flag:
        value = 1
    # end if
    else:
        value = 2
    return value


def not_adjacent() -> int:
    if True:
        value = 1
    value += 1
    # end if
    return value


def bad_nesting() -> None:
    if True:
        for _ in range(1):
            pass
    # end if
        # end for
