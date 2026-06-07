"""Various utilities for other modules."""

import datetime as dt
from collections.abc import Callable, Coroutine, Generator, Iterable, Sequence
from copy import copy, deepcopy
from typing import Any

from oocone.model import Area, Consumption, ConsumptionType, PhotovoltaicSummary


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


def all_the_same[T](things: Iterable[T]) -> T:
    iterator = iter(things)
    first = next(iterator)

    if any(item != first for item in iterator):
        msg = "Expected identical values, but found different ones."
        raise ValueError(msg)

    return first


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


def chain_decorators(
    *decorators: Callable[[Callable[..., Any]], Callable[..., Any]],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Chains the given decorators, first to last."""

    def make_wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
        for decorator in decorators:
            func = decorator(func)
        return func

    return make_wrapper


def copy_result[**P, T](
    *, deep: bool
) -> Callable[
    [Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]
]:
    """
    Lets a function return a copy of what the wrapped function returns.

    Args:
        deep: If true, the return value will be copied recursively.
              Else, a shallow copy will take place

    Returns: A decorator.

    """

    def make_wrapper(
        func: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            r = await func(*args, **kwargs)
            if deep:
                return deepcopy(r)
            return copy(r)

        return wrapped

    return make_wrapper


def relevant_consumption_types(area: Area) -> list[ConsumptionType]:
    """Return relevant consumption types for a given area in the enocoo dashboard."""
    if area.name.startswith("SP"):  # parking space, only electricity is available
        relevant_consumption_types = [ConsumptionType.ELECTRICITY]
    else:
        relevant_consumption_types = list(ConsumptionType)
    return relevant_consumption_types
