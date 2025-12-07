"""Sensor platform for enocoo."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import consumption, meter, quarter, traffic_light

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from ..data import EnocooConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnocooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    for category in consumption, traffic_light, quarter, meter:
        await category.async_setup_entry(hass, entry, async_add_entities)
