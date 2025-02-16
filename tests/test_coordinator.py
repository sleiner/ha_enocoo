"""Tests for the coordinator part of the integration."""

import pytest

from custom_components.ha_enocoo import coordinator


@pytest.mark.asyncio
async def test_bisect_begin() -> None:
    """Tests _bisect for cases where the result is expected to be 0."""

    async def identity[T](x: T) -> T:
        return x

    for array_length in range(1, 4):
        a = [True] * array_length

        actual_result = await coordinator._bisect(a, identity)  # noqa: SLF001
        assert actual_result == 0


@pytest.mark.asyncio
async def test_bisect_middle() -> None:
    """Tests _bisect for cases where result is expected to be 0 < result < len(a)."""

    async def identity[T](x: T) -> T:
        return x

    for num_false in range(1, 3):
        a = ([False] * num_false) + ([True] * 3)

        actual_result = await coordinator._bisect(a, identity)  # noqa: SLF001
        assert actual_result == num_false


@pytest.mark.asyncio
async def test_bisect_end() -> None:
    """Tests _bisect for cases where the result is expected to be len(a) - 1."""

    async def identity[T](x: T) -> T:
        return x

    for num_false in range(1, 3):
        a = ([False] * num_false) + [True]

        actual_result = await coordinator._bisect(a, identity)  # noqa: SLF001
        assert actual_result == len(a) - 1


@pytest.mark.asyncio
async def test_bisect_notfound() -> None:
    """Tests _bisect for cases where key(x) is False for all x in a."""

    async def identity[T](x: T) -> T:
        return x

    for num_false in range(1, 4):
        a = [False] * num_false

        with pytest.raises(RuntimeError, match="StopIteration"):
            await coordinator._bisect(a, identity)  # noqa: SLF001
