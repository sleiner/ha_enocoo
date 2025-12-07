"""
Custom integration to integrate enocoo with Home Assistant.

For more details about this integration, please refer to
https://github.com/sleiner/ha_enocoo
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, override

from async_lru import alru_cache
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, Platform
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util
from oocone import Auth, Enocoo

from ._util import chain_decorators, copy_result
from .const import UPDATE_INTERVAL
from .coordinator import EnocooUpdateCoordinator
from .data import EnocooRuntimeData

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from oocone.model import Area

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
        auth_factory=lambda: Auth(
            base_url=entry.data[CONF_URL],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            websession=async_create_clientsession(hass),
        )
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
    await hass.config_entries.async_reload(entry.entry_id)


class CachedEnocoo(Enocoo):
    """Subclass of oocone.Enocoo with appropriate caching for our use case."""

    def __init__(self, auth_factory: Callable[[], Auth]) -> None:
        """Create a new instane."""
        self._auth_factory = auth_factory
        super().__init__(
            auth=self._auth_factory(), timezone=dt_util.get_default_time_zone()
        )

    __meter_cache = chain_decorators(
        alru_cache(
            # TTL should be close to but less than the polling interval:
            ttl=UPDATE_INTERVAL.seconds - 60,
            # we have a fairly short TTL, but possibly much data to query (think 5 years
            # of daily data), so let's store a large number of items in the cache here.
            maxsize=5000,
        ),
        # Always copy the result after it comes from the cache - to prevent
        # modifications of the cached object by function users. In this case, a deep
        # copy is not necessary, since the return value is a list of frozen dataclasses.
        copy_result(deep=False),
    )

    _get_quarter_photovoltaic_data_uncompensated = __meter_cache(
        Enocoo._get_quarter_photovoltaic_data_uncompensated  # noqa: SLF001
    )
    _get_individual_consumption_uncompensated = __meter_cache(
        Enocoo._get_individual_consumption_uncompensated  # noqa: SLF001
    )

    # The list of areas is special: It is only ever refreshed after a login. Since we
    # also read the dates for which data is available from the returned data, we need to
    # ensure that we re-login once daily. To do this, we cache the result of
    # Enocoo.get_areas(), but add the current date as a cache key. On every cache miss,
    # the web session is reset, so we log in again.

    @override
    async def get_areas(self) -> list[Area]:
        return await self.__get_areas(
            _current_date=dt.datetime.now(tz=dt_util.get_default_time_zone()).date()
        )

    @alru_cache(maxsize=1)
    async def __get_areas(self, *, _current_date: dt.date) -> list[Area]:
        # The API's return value for the areas is only refreshed after login, so we log
        # in again:
        self.auth = self._auth_factory()

        return await super().get_areas()
