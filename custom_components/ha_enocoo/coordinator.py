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
from oocone.model import (
    Area,
    Consumption,
    ConsumptionType,
    PhotovoltaicSummary,
    Quantity,
)

from .const import DOMAIN, LOGGER
from .data import EnocooConfigEntry, EnocooDashboardData

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Coroutine, Sequence
    from typing import Any, Literal

    from homeassistant.core import HomeAssistant

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
            for area in await self.enocoo.get_areas():
                for consumption_type in self.__relevant_consumption_types(area):
                    await self._insert_individual_consumption_statistics(
                        area=area, consumption_type=consumption_type
                    )

            for name, id_suffix, pv_attribute in (
                ("Siedlung Stromverbrauch",  "quarter_consumption",      "consumption"),
                ("Siedlung Stromproduktion", "quarter_generation",       "generation"),
                ("Siedlung Netzbezug",       "quarter_supply_from_grid", "calculated_supply_from_grid"),  # noqa: E501
                ("Siedlung Netzeinspeisung", "quarter_feed_into_grid",   "calculated_feed_into_grid"),  # noqa: E501
            ):  # fmt:skip
                await self._insert_quarter_photovoltaic_statistics(
                    name, id_suffix, pv_attribute
                )

    @staticmethod
    def __relevant_consumption_types(area: Area) -> list[ConsumptionType]:
        if area.name.startswith("SP"):  # parking space, only electricity is available
            relevant_consumption_types = [ConsumptionType.ELECTRICITY]
        else:
            relevant_consumption_types = list(ConsumptionType)
        return relevant_consumption_types

    async def _find_last_stats(
        self, statistic_id: str, now: dt.datetime
    ) -> tuple[dt.datetime | None, dt.datetime | None, float, bool]:
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

        not_expecting_newer_data = last_stats_end_time and (
            now - last_stats_end_time
        ) <= dt.timedelta(minutes=75)
        expecting_newer_data = not not_expecting_newer_data

        return (
            last_stats_time,
            last_stats_end_time,
            consumption_sum,
            expecting_newer_data,
        )

    @staticmethod
    def _reading_is_usable(
        hourly_reads: Sequence[Consumption | PhotovoltaicSummary],
        last_stats_time: dt.datetime | None,
    ) -> bool:
        start = hourly_reads[0].start
        if last_stats_time is not None and start <= last_stats_time:
            return False  # reading is too old

        period = sum((r.period for r in hourly_reads), start=dt.timedelta(0))
        if period != dt.timedelta(hours=1):  # noqa: SIM103
            return False  # hour is not complete

        return True

    async def _insert_individual_consumption_statistics(
        self, area: Area, consumption_type: ConsumptionType
    ) -> None:
        statistic_id = self._statistic_id_individual_consumption(area, consumption_type)
        now = dt.datetime.now(tz=dt_util.get_default_time_zone())
        (
            last_stats_time,
            last_stats_end_time,
            consumption_sum,
            expecting_newer_data,
        ) = await self._find_last_stats(statistic_id, now)

        if not expecting_newer_data:
            # Statistics for a full hour are available about 15 minutes after the hour
            # has concluded.
            LOGGER.debug(
                "%s statistics for the next full hour are not yet available."
                " Skipping statistics collection...",
                consumption_type,
            )
            return

        async def get_dates_to_query() -> AsyncGenerator[dt.date]:
            if last_stats_time is None:
                date = await self._find_earliest_consumption_statistics(
                    consumption_type=consumption_type, area=area
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
                area_id=area.id,
            )

            for unit, reads in groupby(all_reads, lambda read: read.unit):
                new_stats = []
                for _, hourly_reads_it in groupby(reads, lambda read: read.start.hour):
                    hourly_reads = list(hourly_reads_it)
                    if not self._reading_is_usable(hourly_reads, last_stats_time):
                        continue

                    consumption = sum(r.value for r in hourly_reads)
                    consumption_sum += consumption
                    new_stats.append(
                        StatisticData(
                            start=hourly_reads[0].start,
                            state=consumption,
                            sum=consumption_sum,
                        )
                    )

                stat_metadata = StatisticMetaData(
                    has_mean=False,
                    has_sum=True,
                    name=self._statistic_name_individual_consumption(
                        area, consumption_type
                    ),
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement=unit,
                )
                async_add_external_statistics(self.hass, stat_metadata, new_stats)

    async def _insert_quarter_photovoltaic_statistics(
        self,
        name: str,
        id_suffix: str,
        pv_summary_attribute_name: str,
    ) -> None:
        statistic_id = self._statistic_id(id_suffix)

        now = dt.datetime.now(tz=dt_util.get_default_time_zone())
        (
            last_stats_time,
            last_stats_end_time,
            consumption_sum,
            expecting_newer_data,
        ) = await self._find_last_stats(statistic_id, now)

        if not expecting_newer_data:
            # Statistics for a full hour are available about 15 minutes after the hour
            # has concluded.
            LOGGER.debug(
                "Photovoltaic %s statistics for the next full hour are not yet "
                "available. Skipping statistics collection...",
                name,
            )
            return

        async def get_dates_to_query() -> AsyncGenerator[dt.date]:
            if last_stats_time is None:
                date = await self._find_earliest_photovoltaic_data()
                if date is None:
                    msg = (
                        "Could not find individual consumption statistics"
                        " on enocoo Dashboard."
                    )
                    raise UpdateFailed(msg)

                LOGGER.info(
                    "No history for photovoltaic %s is recorded yet."
                    " Querying all data from enocoo, since the first data point on %s."
                    " This might take a while...",
                    name,
                    date.isoformat(),
                )
            else:
                date = last_stats_time.date()

            today = now.date()
            while date <= today:
                yield date
                date += dt.timedelta(1)

        def get_quantity(pv: PhotovoltaicSummary) -> Quantity:
            return getattr(pv, pv_summary_attribute_name)

        async for date in get_dates_to_query():
            all_reads = await self.enocoo.get_quarter_photovoltaic_data(
                during=date, interval="day"
            )

            for unit, reads in groupby(all_reads, lambda read: get_quantity(read).unit):
                new_stats = []
                for _, hourly_reads_it in groupby(reads, lambda read: read.start.hour):
                    hourly_reads = list(hourly_reads_it)
                    if not self._reading_is_usable(hourly_reads, last_stats_time):
                        continue

                    consumption = sum(get_quantity(r).value for r in hourly_reads)
                    consumption_sum += consumption
                    new_stats.append(
                        StatisticData(
                            start=hourly_reads[0].start,
                            state=consumption,
                            sum=consumption_sum,
                        )
                    )

                stat_metadata = StatisticMetaData(
                    has_mean=False,
                    has_sum=True,
                    name=f"{self.config_entry.title} {name}".strip(),
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement=unit,
                )
                async_add_external_statistics(self.hass, stat_metadata, new_stats)

    def _statistic_id_individual_consumption(
        self, area: Area, consumption_type: ConsumptionType
    ) -> str:
        statistic_id = self._statistic_id(suffix=f"{area.id}_{consumption_type}")
        LOGGER.debug(
            "Statistics ID for %s in area %s: %s",
            consumption_type,
            area.id,
            statistic_id,
        )
        return statistic_id

    def _statistic_id(self, suffix: str) -> str:
        return (
            f"{self.config_entry.domain}:{self.config_entry.entry_id}_{suffix}".lower()
        )

    def _statistic_name_individual_consumption(
        self, area: Area, consumption_type: ConsumptionType
    ) -> str:
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

        return f"{area.name} {consumption_name}"

    async def _find_earliest_photovoltaic_data(self) -> dt.date | None:
        async def get_timestamps(
            interval: Literal["day", "month"], during: dt.date
        ) -> list[dt.datetime]:
            datapoints = await self.enocoo.get_quarter_photovoltaic_data(
                interval=interval, during=during
            )
            return [datapoint.start for datapoint in datapoints]

        return await self._find_earliest_datapoint(get_timestamps)

    async def _find_earliest_consumption_statistics(
        self,
        consumption_type: ConsumptionType,
        area: Area,
    ) -> dt.date | None:
        async def get_timestamps(
            interval: Literal["day", "month", "year"], during: dt.date
        ) -> list[dt.datetime]:
            readings = await self.enocoo.get_individual_consumption(
                consumption_type,
                during=during,
                interval=interval,
                area_id=area.id,
                compensate_off_by_one=False,
            )
            return [reading.start for reading in readings]

        return await self._find_earliest_datapoint(get_timestamps)

    async def _find_earliest_datapoint(
        self,
        get_timestamps: Callable[
            [Literal["month"], dt.date], Coroutine[Any, Any, list[dt.datetime]]
        ],
    ) -> dt.date | None:
        today = dt.datetime.now(tz=dt_util.get_default_time_zone()).date()
        months = self.__months_between(dt.date(2000, 1, 1), today)

        async def has_timestamps(month: dt.date) -> bool:
            timestamps = await get_timestamps("month", month)
            return len(timestamps) > 0

        try:
            earliest_month_idx = await _bisect(months, has_timestamps)
        except Exception:  # noqa: BLE001
            return None
        else:
            earliest_month = months[earliest_month_idx]
            timestamps = await get_timestamps("month", earliest_month)
            return sorted(timestamps)[0].date()

    @staticmethod
    def __months_between(from_date: dt.date, to_date: dt.date) -> list[dt.date]:
        num_months_per_year = 12
        firsts_of_months = []
        date = from_date

        while date <= to_date:
            firsts_of_months.append(date)
            year_increment, month_zerobased = divmod(date.month, num_months_per_year)
            date = dt.date(date.year + year_increment, month_zerobased + 1, 1)

        return firsts_of_months


async def _bisect[T](
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
