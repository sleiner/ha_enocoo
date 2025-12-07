"""DataUpdateCoordinator for enocoo."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

import oocone
import oocone.errors
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._statistics import StatisticsInserter
from ._util import relevant_consumption_types
from .const import DOMAIN, LOGGER, UPDATE_INTERVAL
from .data import EnocooConfigEntry, EnocooDashboardData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from oocone.model import (
        Area,
        Consumption,
        ConsumptionType,
        PhotovoltaicSummary,
    )

    from .data import DailyConsumption, DailyConsumptionForArea, EnocooConfigEntry


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
        # During any actual use, these will not be None. To not fight with None-ness all
        # the time, we annotate them as such.
        self.latest_expected_datapoint_time: dt.datetime = None  # type: ignore[assignment]
        self.latest_update_start_time: dt.datetime = None  # type: ignore[assignment]

    async def _async_update_data(self) -> EnocooDashboardData:
        """Update data via library."""
        now = dt.datetime.now(self.enocoo.timezone)
        self.latest_update_start_time = now
        self.latest_expected_datapoint_time = now - 2 * UPDATE_INTERVAL

        try:
            dashboard_data = EnocooDashboardData(
                traffic_light_status=await self.enocoo.get_traffic_light_status(),
                meter_table=await self.enocoo.get_meter_table(
                    allow_previous_day_until=dt.time(23, 45)
                ),
                current_photovoltaic_data=await self._get_latest_photovoltaic_data(),
                current_individual_consumption=await self._get_latest_individual_consumption(),  # noqa: E501
            )
        except oocone.errors.AuthenticationFailed as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except oocone.errors.OoconeError as exception:
            raise UpdateFailed(exception) from exception

        await self.statistics_inserter.trigger_insertion()
        return dashboard_data

    async def _get_latest_photovoltaic_data(self) -> PhotovoltaicSummary | None:
        if pv_data := await self.enocoo.get_quarter_photovoltaic_data(
            during=self.latest_expected_datapoint_time.date(), interval="day"
        ):
            return pv_data[-1]

        return None

    async def _get_latest_individual_consumption(self) -> DailyConsumption:
        async def get_all() -> DailyConsumption:
            areas = await self.enocoo.get_areas()
            consumptions = await asyncio.gather(*(get_for_area(a) for a in areas))
            area_ids = [area.id for area in areas]
            return dict(zip(area_ids, consumptions, strict=True))

        async def get_for_area(area: Area) -> DailyConsumptionForArea:
            types = relevant_consumption_types(area)
            consumptions = await asyncio.gather(
                *(get_for_area_and_type(area, t) for t in types)
            )
            return dict(zip(types, consumptions, strict=True))

        async def get_for_area_and_type(
            area: Area, type_: ConsumptionType
        ) -> Consumption | None:
            date = self.latest_expected_datapoint_time.date()
            error_log_line = (
                f"Fetching of {type_} consumption "
                f"during {date} in area {area.name} failed"
            )

            try:
                consumptions = await self.enocoo.get_individual_consumption(
                    type_, interval="day", during=date, area_id=area.id
                )
            except oocone.errors.OoconeError as exc:
                LOGGER.error("%s: %s", error_log_line, exc)
                return None
            if not consumptions:
                LOGGER.error("%s: No data for date are available.", error_log_line)
                return None

            latest_datapoint = consumptions[-1]
            datapoint_end_time = latest_datapoint.start + latest_datapoint.period
            highest_acceptable_delay = (2 * UPDATE_INTERVAL) + dt.timedelta(minutes=1)
            actual_delay = self.latest_update_start_time - datapoint_end_time
            if actual_delay > highest_acceptable_delay:
                LOGGER.error(
                    "%s: The latest datapoint ended at %s, which is more than %s ago."
                    " Discarding...",
                    error_log_line,
                    datapoint_end_time,
                    highest_acceptable_delay,
                )
                return None

            return latest_datapoint

        return await get_all()
