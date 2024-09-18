"""DataUpdateCoordinator for enocoo."""

from __future__ import annotations

import datetime as dt
from asyncio import Lock
from itertools import groupby
from typing import TYPE_CHECKING, cast

import oocone
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from oocone.types import ConsumptionType

from .const import DOMAIN, LOGGER
from .data import EnocooConfigEntry, EnocooDashboardData

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant

    from .data import EnocooConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class EnocooUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: EnocooConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: EnocooConfigEntry,
        enocoo: oocone.enocoo,
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
            )
        except oocone.errors.AuthenticationFailed as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except oocone.errors.OoconeError as exception:
            raise UpdateFailed(exception) from exception

        await self.statistics_inserter.trigger_insertion()
        return dashboard_data


class StatisticsInserter:
    """Inserts historical data into the recorder component of Home Assistant."""

    def __init__(
        self,
        hass: HomeAssistant,
        enocoo: oocone.Enocoo,
        config_entry: EnocooConfigEntry,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.enocoo = enocoo
        self.config_entry = config_entry
        self.insertion_in_progress = Lock()

    async def trigger_insertion(self) -> None:
        """Trigger the collection and insertion of statistics."""
        if not self.insertion_in_progress.locked():
            self.hass.async_create_task(self._insert_statistics())

    async def _insert_statistics(self) -> None:
        async with self.insertion_in_progress:
            for area_id in await self.enocoo.get_area_ids():
                for consumption_type in ConsumptionType:
                    await self._insert_individual_consumption_statistics(
                        area_id=area_id, consumption_type=consumption_type
                    )

    async def _insert_individual_consumption_statistics(
        self, area_id: str, consumption_type: ConsumptionType
    ) -> None:
        statistic_id = self._statistic_id(area_id, consumption_type)
        old_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            statistic_id,
            True,  # noqa: FBT003
            set(),
        )
        if old_stats:
            last_stats_time = dt.datetime.fromtimestamp(
                old_stats[statistic_id][0]["start"], tz=dt_util.get_default_time_zone()
            )
            last_stats_end_time = dt.datetime.fromtimestamp(
                old_stats[statistic_id][0]["end"], tz=dt_util.get_default_time_zone()
            )
            last_stat = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                last_stats_time,
                None,
                {statistic_id},
                "hour",
                None,
                {"sum"},
            )
            consumption_sum = cast(float, last_stat[statistic_id][0]["sum"])
        else:
            last_stats_time = None
            last_stats_end_time = None
            consumption_sum = 0.0

        now = dt.datetime.now(tz=dt_util.get_default_time_zone())
        if last_stats_end_time and (now - last_stats_end_time) <= dt.timedelta(
            minutes=75
        ):
            # Statistics for a full hour are available about 15 minutes after the hour
            # has concluded.
            LOGGER.debug(
                "%s statistics for the next full hour are not yet available."
                " Skipping statistics collection...",
                consumption_type,
            )
            return

        async def get_dates_to_query() -> Generator[dt.date]:
            if last_stats_time is None:
                date = await self._find_earliest_consumption_statistics(
                    consumption_type=consumption_type, area_id=area_id
                )
                if date is None:
                    msg = (
                        "Could not find individual consumption statistics"
                        " on enocoo Dashboard."
                    )
                    raise UpdateFailed(msg)

                LOGGER.info(
                    "No history for %s is recorded yet."
                    " Querying all data from enocoo, since the first data point on %s."
                    " This might take a while...",
                    consumption_type,
                    date.isoformat(),
                )
            else:
                date = last_stats_time.date()

            today = now.date()
            while date <= today:
                yield date
                date += dt.timedelta(1)

        async for date in get_dates_to_query():
            all_reads = await self.enocoo.get_individual_consumption(
                consumption_type=consumption_type,
                during=date,
                interval="day",
                area_id=area_id,
            )

            for unit, reads in groupby(all_reads, lambda read: read.unit):
                new_stats = []
                for _, hourly_reads_it in groupby(reads, lambda read: read.start.hour):
                    hourly_reads = list(hourly_reads_it)

                    start = hourly_reads[0].start
                    if last_stats_time is not None and start <= last_stats_time:
                        # reading is too old
                        continue

                    period = sum(
                        (r.period for r in hourly_reads), start=dt.timedelta(0)
                    )
                    if period != dt.timedelta(hours=1):
                        # hour is not complete
                        continue

                    consumption = sum(r.value for r in hourly_reads)
                    consumption_sum += consumption
                    new_stats.append(
                        StatisticData(
                            start=start,
                            state=consumption,
                            sum=consumption_sum,
                        )
                    )

                stat_metadata = StatisticMetaData(
                    has_mean=False,
                    has_sum=True,
                    name=self._statistic_name(area_id, consumption_type),
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement=unit,
                )
                async_add_external_statistics(self.hass, stat_metadata, new_stats)

    def _statistic_id(self, area_id: str, consumption_type: ConsumptionType) -> str:
        statistic_id = (
            f"{self.config_entry.domain}:"
            f"{self.config_entry.entry_id}_"
            f"{area_id}_"
            f"{consumption_type}"
        ).lower()
        LOGGER.debug(
            "Statistics ID for %s in area %s: %s",
            consumption_type,
            area_id,
            statistic_id,
        )
        return statistic_id

    def _statistic_name(self, area_id: str, consumption_type: ConsumptionType) -> str:
        # Unfortunately, statistics names cannot be internationalized :/
        # Since this integration is mostly used in Germany, we use german names.

        if consumption_type == ConsumptionType.ELECTRICITY:
            consumption_name = "Strom"
        elif consumption_type == ConsumptionType.WATER_COLD:
            consumption_name = "Kaltwasser"
        elif consumption_type == ConsumptionType.WATER_HOT:
            consumption_name = "Warmwasser"
        elif consumption_type == ConsumptionType.HEAT:
            consumption_name = "Wärme"
        else:
            consumption_name = str(consumption_type)

        return f"{self.config_entry.title} {area_id} {consumption_name}"

    async def _find_earliest_consumption_statistics(
        self,
        consumption_type: ConsumptionType,
        area_id: str,
    ) -> dt.date | None:
        earliest_year = None
        for year in range(
            dt.datetime.now(tz=dt_util.get_default_time_zone()).year,
            2000,
            -1,
        ):
            yearly_readings = await self.enocoo.get_individual_consumption(
                consumption_type,
                during=dt.date(year, 1, 1),
                interval="year",
                area_id=area_id,
            )
            if len(yearly_readings) > 0:
                earliest_year_readings = yearly_readings
                earliest_year = year
            else:
                break

        if earliest_year is None:
            return None

        earliest_month = min(c.start.month for c in earliest_year_readings)
        date = dt.date(earliest_year, earliest_month, 1)
        while date.month == earliest_month:
            daily_readings = await self.enocoo.get_individual_consumption(
                consumption_type, during=date, interval="day", area_id=area_id
            )

            if len(daily_readings) == 0:
                date = date + dt.timedelta(days=1)
            else:
                break

        return date
