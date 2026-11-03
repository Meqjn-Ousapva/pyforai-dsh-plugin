"""Edge-case module: decorators, async, match, try/finally, for/else, one-line."""

from __future__ import annotations


@deco
@other(arg=1)
def decorated(x: int) -> int:
    if x > 0:
        return x
    # end if
    return -x
# end def


async def worker(items):
    async for item in items:
        async with lock:
            if item:
                use(item)
            # end if
        # end with
    # end for
    return None
# end def


def classify(value):
    match value:
        case 1:
            return "one"
        case _ if value > 0:
            return "positive"
        case _:
            return "other"
    # end match
# end def


def loop_else(xs):
    for x in xs:
        if x:
            use(x)
        # end if
    else:
        done()
    # end for
    return None
# end def


def try_finally():
    try:
        work()
    except ValueError:
        recover()
    else:
        ok()
    finally:
        cleanup()
    # end try
# end def


if flag: use(flag)
# end if
