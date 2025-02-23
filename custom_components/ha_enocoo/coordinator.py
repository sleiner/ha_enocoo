"""DataUpdateCoordinator for enocoo."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import oocone
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._statistics import StatisticsInserter
from .const import DOMAIN, LOGGER
from .data import EnocooConfigEntry, EnocooDashboardData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from oocone.model import (
        PhotovoltaicSummary,
    )

    from .data import EnocooConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class EnocooUpdateCoordinator(DataUpdateCoordinator[EnocooDashboardData]):
    """Class to manage fetching data from the API."""

    config_entry: EnocooConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: EnocooConfigEntry,
        enocoo: oocone.enocoo.Enocoo,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=dt.timedelta(minutes=15),
            always_update=False,
        )
        self.config_entry = config_entry
        self.enocoo = enocoo
        self.statistics_inserter = StatisticsInserter(
            self.hass, self.enocoo, self.config_entry
        )

    async def _async_update_data(self) -> EnocooDashboardData:
        """Update data via library."""
        try:
            dashboard_data = EnocooDashboardData(
                traffic_light_status=await self.enocoo.get_traffic_light_status(),
                meter_table=await self.enocoo.get_meter_table(
                    allow_previous_day_until=dt.time(23, 45)
                ),
                current_photovoltaic_data=await self._get_latest_photovoltaic_data(),
            )
        except oocone.errors.AuthenticationFailed as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except oocone.errors.OoconeError as exception:
            raise UpdateFailed(exception) from exception

        await self.statistics_inserter.trigger_insertion()
        return dashboard_data

    async def _get_latest_photovoltaic_data(self) -> PhotovoltaicSummary | None:
        today = dt.datetime.now(self.enocoo.timezone).date()
        for num_days_back in range(3):
            date = today - dt.timedelta(days=num_days_back)

            if pv_data := await self.enocoo.get_quarter_photovoltaic_data(
                during=date, interval="day"
            ):
                return pv_data[-1]

        return None
