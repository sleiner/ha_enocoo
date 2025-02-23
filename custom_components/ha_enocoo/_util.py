"""Various utilities for other modules."""

import datetime as dt
from collections.abc import Callable, Coroutine, Generator, Sequence

from oocone.model import Consumption, PhotovoltaicSummary


async def bisect[T](
    a: Sequence[T], key: Callable[[T], Coroutine[None, None, bool]]
) -> int:
    """
    Find the first element in a, where key(a) = True (assuming key(a) is ordered).

    Assuming that a is a sequence and key assigns a boolean to each element in such that
    key(a) is a step function (i.e. for the first part of a, key(x) is False and for the
    second part key(x) is True), this function returns the index of the first element x
    where key(x) is True.

    This code is adapted from the Python standard library's bisect module [1].
    Copyright (c) 2001-2025 Python Software Foundation; All Rights Reserved

    [1]: https://github.com/python/cpython/blob/3.13/Lib/bisect.py
    """
    lo = 0
    hi = len(a)

    while lo < hi:
        mid = (lo + hi) // 2
        if await key(a[mid]):
            hi = mid
        else:
            lo = mid + 1

    if lo == len(a):
        msg = "Did not find an element x where key(x) == True."
        raise StopIteration(msg)

    return lo


MeasurementWithinPeriod = Consumption | PhotovoltaicSummary


def zip_measurements[T: MeasurementWithinPeriod, U: MeasurementWithinPeriod](
    measurement_series_1: Sequence[T],
    measurement_series_2: Sequence[U],
    *,
    strict: bool = False,
) -> Generator[tuple[dt.datetime, dt.timedelta, T, U]]:
    for m1, m2 in zip(measurement_series_1, measurement_series_2, strict=strict):
        if m1.start != m2.start:
            msg = f"Start dates {m1.start} and {m2.start} do not match."
            raise ValueError(msg)
        if m1.period != m2.period:
            msg = (
                f"Periods {m1.period} and {m2.period} starting from {m1.start}"
                " do not match."
            )
            raise ValueError(msg)
        yield (m1.start, m1.period, m1, m2)
