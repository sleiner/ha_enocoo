"""
Custom integration to integrate enocoo with Home Assistant.

For more details about this integration, please refer to
https://github.com/sleiner/ha_enocoo
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from async_lru import alru_cache
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util
from oocone import Auth, Enocoo

from .coordinator import EnocooUpdateCoordinator
from .data import EnocooRuntimeData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import EnocooConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
]


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnocooConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    enocoo = CachedEnocoo(
        Auth(
            base_url=entry.data[CONF_URL],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            websession=async_get_clientsession(hass),
        ),
        timezone=dt_util.get_default_time_zone(),
    )
    coordinator = EnocooUpdateCoordinator(hass=hass, config_entry=entry, enocoo=enocoo)
    entry.runtime_data = EnocooRuntimeData(
        client=enocoo,
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: EnocooConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: EnocooConfigEntry,
) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


class CachedEnocoo(Enocoo):
    """Subclass of oocone.Enocoo with appropriate caching for our use case."""

    __meter_cache = alru_cache(
        # TTL should be close to but less then the 15 min polling interval:
        ttl=dt.timedelta(minutes=14).seconds,
        # we have a fairly short TTL, but possibly much data to query (think 5 years of
        # daily data), so let's store a large number of items in the cache here.
        maxsize=5000,
    )

    get_area_ids = alru_cache(ttl=dt.timedelta(hours=23).seconds)(Enocoo.get_area_ids)
    get_quarter_photovoltaic_data = __meter_cache(Enocoo.get_quarter_photovoltaic_data)
    _get_individual_consumption_uncompensated = __meter_cache(
        Enocoo._get_individual_consumption_uncompensated  # noqa: SLF001
    )
