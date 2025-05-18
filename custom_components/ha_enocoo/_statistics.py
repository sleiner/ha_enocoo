"""Writes custom long-term statistics into the Home Assistant database."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from asyncio import Lock
from itertools import groupby
from statistics import mean
from typing import TYPE_CHECKING, ClassVar, Self, cast, override

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from oocone.model import (
    Area,
    Consumption,
    ConsumptionType,
    PhotovoltaicSummary,
    Quantity,
)

from ._util import all_the_same, bisect, zip_measurements
from .const import CONF_NUM_SHARES, CONF_NUM_SHARES_TOTAL, DOMAIN, LOGGER
from .data import EnocooConfigEntry

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Coroutine, Mapping, Sequence
    from typing import Any, Literal

    import oocone
    from homeassistant.core import HomeAssistant

    from .data import EnocooConfigEntry


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

                for metric in IndividualCalculatedMetric.metrics:
                    await self._insert_individual_photovoltaic_statistics(
                        area, metric(self.enocoo)
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

            for subentry in self.config_entry.subentries.values():
                match subentry.subentry_type:
                    case "ownership_shares":
                        await self._insert_surplus_per_share_statistics(subentry.data)

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
            consumption_sum = cast("float", last_stat[statistic_id][0]["sum"])
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

    async def _dates_to_insert_individual_statistics(
        self,
        area: Area,
        statistic_id: str,
    ) -> tuple[bool, AsyncGenerator[dt.date], dt.datetime | None, float]:
        now = dt.datetime.now(tz=dt_util.get_default_time_zone())
        (
            last_stats_time,
            _,
            consumption_sum,
            expecting_newer_data,
        ) = await self._find_last_stats(statistic_id, now)

        if expecting_newer_data:

            async def get_dates_to_query() -> AsyncGenerator[dt.date]:
                if last_stats_time is None:
                    date = area.data_available_since

                    LOGGER.info(
                        "No history for %s is recorded yet. Querying all data from"
                        " enocoo, since the first data point on %s."
                        " This might take a while...",
                        statistic_id,
                        date.isoformat(),
                    )
                else:
                    date = last_stats_time.date()

                newest_date_online = min(
                    now.date(),
                    # Areas are cached for about a day, so data_available_until might be
                    # a day behind. To compensate, we add a day.
                    area.data_available_until + dt.timedelta(days=1),
                )
                while date <= newest_date_online:
                    yield date
                    date += dt.timedelta(1)
        else:

            async def get_dates_to_query() -> AsyncGenerator[dt.date]:
                return
                yield

        return (
            expecting_newer_data,
            get_dates_to_query(),
            last_stats_time,
            consumption_sum,
        )

    async def _dates_to_insert_quarter_pv_statistics(
        self, statistic_id: str
    ) -> tuple[bool, AsyncGenerator[dt.date], dt.datetime | None, float]:
        now = dt.datetime.now(tz=dt_util.get_default_time_zone())
        (
            last_stats_time,
            last_stats_end_time,
            statistic_sum,
            expecting_newer_data,
        ) = await self._find_last_stats(statistic_id, now)

        if expecting_newer_data:

            async def get_dates_to_query() -> AsyncGenerator[dt.date]:
                if last_stats_time is None:
                    date = await self._find_earliest_photovoltaic_data()
                    if date is None:
                        msg = (
                            "Could not find photovoltaic statistics"
                            " on enocoo dashboard."
                        )
                        raise UpdateFailed(msg)

                    LOGGER.info(
                        "No history for %s is recorded yet."
                        " Filling in all data since the first data point on %s."
                        " This might take a while...",
                        statistic_id,
                        date.isoformat(),
                    )
                else:
                    date = last_stats_time.date()

                today = now.date()
                while date <= today:
                    yield date
                    date += dt.timedelta(1)
        else:

            async def get_dates_to_query() -> AsyncGenerator[dt.date]:
                return
                yield

        return (
            expecting_newer_data,
            get_dates_to_query(),
            last_stats_time,
            statistic_sum,
        )

    async def _insert_individual_consumption_statistics(
        self, area: Area, consumption_type: ConsumptionType
    ) -> None:
        statistic_id = self._statistic_id(consumption_type, area=area)
        (
            expecting_newer_data,
            dates_to_query,
            last_stats_time,
            consumption_sum,
        ) = await self._dates_to_insert_individual_statistics(area, statistic_id)

        if not expecting_newer_data:
            # Statistics for a full hour are available about 15 minutes after the hour
            # has concluded.
            LOGGER.debug(
                "%s statistics in %s for the next full hour are not yet available."
                " Skipping statistics collection...",
                consumption_type,
                area.name,
            )
            return

        async for date in dates_to_query:
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
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=self._statistic_name_individual(area, consumption_type),
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement=unit,
                )
                async_add_external_statistics(self.hass, stat_metadata, new_stats)

    async def _insert_individual_photovoltaic_statistics(
        self, area: Area, metric: IndividualCalculatedMetric
    ) -> None:
        statistic_id = self._statistic_id(metric.id_suffix, area=area)
        (
            expecting_newer_data,
            dates_to_query,
            last_stats_time,
            overall_sum,
        ) = await self._dates_to_insert_individual_statistics(area, statistic_id)

        if not expecting_newer_data:
            # Statistics for a full hour are available about 15 minutes after the hour
            # has concluded.
            LOGGER.debug(
                "%s statistics in %s for the next full hour are not yet available."
                " Skipping statistics collection...",
                metric.id_suffix,
                area.name,
            )
            return

        async for date in dates_to_query:
            all_reads = await metric.get_daily_datapoints(area, date)

            for unit, reads in groupby(all_reads, lambda read: read.unit):
                new_stats = []
                for _, hourly_reads_it in groupby(reads, lambda read: read.start.hour):
                    hourly_reads = list(hourly_reads_it)
                    if not self._reading_is_usable(hourly_reads, last_stats_time):
                        continue

                    hourly_sum = sum(r.value for r in hourly_reads)
                    overall_sum += hourly_sum
                    new_stats.append(
                        StatisticData(
                            start=hourly_reads[0].start,
                            state=hourly_sum,
                            sum=overall_sum,
                        )
                    )

                stat_metadata = StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=self._statistic_name_individual(area, metric),
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

        (
            expecting_newer_data,
            dates_to_query,
            last_stats_time,
            statistic_sum,
        ) = await self._dates_to_insert_quarter_pv_statistics(statistic_id)

        if not expecting_newer_data:
            # Statistics for a full hour are available about 15 minutes after the hour
            # has concluded.
            LOGGER.debug(
                "Photovoltaic %s statistics for the next full hour are not yet "
                "available. Skipping statistics collection...",
                name,
            )
            return

        def get_quantity(pv: PhotovoltaicSummary) -> Quantity:
            return getattr(pv, pv_summary_attribute_name)

        async for date in dates_to_query:
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
                    statistic_sum += consumption
                    new_stats.append(
                        StatisticData(
                            start=hourly_reads[0].start,
                            state=consumption,
                            sum=statistic_sum,
                        )
                    )

                stat_metadata = StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=f"{self.config_entry.title} {name}".strip(),
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement=unit,
                )
                async_add_external_statistics(self.hass, stat_metadata, new_stats)

    async def _insert_surplus_per_share_statistics(
        self, subentry_data: Mapping[str, Any]
    ) -> None:
        share_factor = (
            subentry_data[CONF_NUM_SHARES] / subentry_data[CONF_NUM_SHARES_TOTAL]
        )
        await self._derive_statistic(
            statistic_id=self._statistic_id(
                f"per_share_{slugify(subentry_data[CONF_NAME])}_feed_into_grid"
            ),
            name=f"{subentry_data[CONF_NAME]} anteilige Netzeinspeisung",
            base_statistic_id=self._statistic_id("quarter_feed_into_grid"),
            transform_datapoint=lambda value: value * share_factor,
        )

    async def _derive_statistic(
        self,
        *,
        statistic_id: str,
        name: str,
        base_statistic_id: str,
        transform_datapoint: Callable[[float], float],
    ) -> None:
        (
            expecting_newer_data,
            dates_to_query,
            last_stats_time,
            statistic_sum,
        ) = await self._dates_to_insert_quarter_pv_statistics(statistic_id)

        if not expecting_newer_data:
            LOGGER.debug(
                "%s statistics for the next full hour are not yet available."
                " Skipping statistics collection...",
                name,
            )
            return

        first_date_to_query = await dates_to_query.__anext__()
        query_start = last_stats_time or dt.datetime.combine(
            first_date_to_query, dt.time(), self.enocoo.timezone
        )

        _, base_metadata = (
            await get_instance(self.hass).async_add_executor_job(
                lambda: get_metadata(self.hass, statistic_ids={base_statistic_id})
            )
        )[base_statistic_id]
        base_stats = (
            await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                query_start,
                None,
                {base_statistic_id},
                "hour",
                None,
                {"state", "sum"},
            )
        )[base_statistic_id]

        new_stats = []
        for base_stat in base_stats:
            if base_stat["state"] is None:
                new_state = None
            else:
                new_state = transform_datapoint(base_stat["state"])
                statistic_sum += new_state
            new_stat = {
                **base_stat,
                "start": dt.datetime.fromtimestamp(base_stat["start"], dt.UTC),
                "state": new_state,
                "sum": statistic_sum,
            }
            for field_name in ("min", "max", "mean"):
                if (base_field := base_stat.get(field_name, None)) is not None:
                    base_field = cast("float", base_field)
                    new_stat[field_name] = transform_datapoint(base_field)
            new_stats.append(StatisticData(**new_stat))  # type: ignore[typeddict-item]

        new_metadata = StatisticMetaData(
            **{
                **base_metadata,
                "name": name,
                "statistic_id": statistic_id,
                "source": DOMAIN,
            }
        )

        async_add_external_statistics(self.hass, new_metadata, new_stats)

    def _statistic_id(self, suffix: str, *, area: Area | None = None) -> str:
        prefix = f"{self.config_entry.domain}:{self.config_entry.entry_id}"
        rest = f"{area.id}_{suffix}" if area else suffix
        statistic_id = f"{prefix}_{rest}".lower()

        LOGGER.debug(
            "Statistics ID for %s: %s",
            rest,
            statistic_id,
        )

        return statistic_id

    def _statistic_name_individual(
        self, area: Area, statistic_type: ConsumptionType | IndividualCalculatedMetric
    ) -> str:
        # Unfortunately, statistics names cannot be internationalized :/
        # Since this integration is mostly used in Germany, we use german names.

        if statistic_type == ConsumptionType.ELECTRICITY:
            name_suffix = "Strom"
        elif statistic_type == ConsumptionType.WATER_COLD:
            name_suffix = "Kaltwasser"
        elif statistic_type == ConsumptionType.WATER_HOT:
            name_suffix = "Warmwasser"
        elif statistic_type == ConsumptionType.HEAT:
            name_suffix = "Wärme"
        elif isinstance(statistic_type, IndividualCalculatedMetric):
            name_suffix = statistic_type.name_suffix
        else:
            name_suffix = str(statistic_type)

        return f"{area.name} {name_suffix}"

    async def _find_earliest_photovoltaic_data(self) -> dt.date | None:
        async def get_timestamps(
            interval: Literal["day", "month"], during: dt.date
        ) -> list[dt.datetime]:
            datapoints = await self.enocoo.get_quarter_photovoltaic_data(
                interval=interval, during=during
            )
            return [datapoint.start for datapoint in datapoints]

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
            earliest_month_idx = await bisect(months, has_timestamps)
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


Datapoint = Consumption


class IndividualCalculatedMetric(ABC):
    metrics: ClassVar[list[type[Self]]] = []

    def __init_subclass__(cls) -> None:
        IndividualCalculatedMetric.metrics.append(cls)

    def __init__(self, enocoo: oocone.Enocoo) -> None:
        self.enocoo = enocoo

    @property
    @abstractmethod
    def id_suffix(self) -> str:
        """Suffix for the statistic ID, identifying the metric."""

    @property
    @abstractmethod
    def name_suffix(self) -> str:
        """Suffix for the statistic name, identifying the metric."""

    @abstractmethod
    def calculate_datapoint(
        self,
        start: dt.datetime,
        period: dt.timedelta,
        electricity_consumption: Consumption,
        pv: PhotovoltaicSummary,
    ) -> Datapoint:
        """Calculate a single datapoint for a given point in time."""

    async def get_daily_datapoints(self, area: Area, date: dt.date) -> list[Datapoint]:
        """Return all datapoints for a given day and area."""

        def group_by_hour[T: Consumption | PhotovoltaicSummary](
            reads: Sequence[T],
        ) -> dict[int, Sequence[T]]:
            return {
                hour: list(reads)
                for hour, reads in groupby(reads, lambda read: read.start.hour)
            }

        daily_consumption = await self.enocoo.get_individual_consumption(
            ConsumptionType.ELECTRICITY, area_id=area.id, interval="day", during=date
        )
        consumption_by_hour = group_by_hour(daily_consumption)

        daily_pv_stats = await self.enocoo.get_quarter_photovoltaic_data(
            interval="day", during=date
        )
        pv_stats_by_hour = group_by_hour(daily_pv_stats)

        datapoints = []
        last_hour = min(
            max(consumption_by_hour.keys(), default=0),
            max(pv_stats_by_hour.keys(), default=0),
        )
        for hour in range(last_hour + 1):
            try:
                consumptions = consumption_by_hour[hour]
            except KeyError:
                LOGGER.error(
                    "Did not find consumption data for area %s"
                    " at %s between %02d:00 and %02d:00."
                    " %s (%s) statistics for this time will be missing!",
                    area.name,
                    date.isoformat(),
                    hour,
                    hour + 1,
                    self.name_suffix,
                    self.id_suffix,
                )
                continue
            try:
                pv_stats = pv_stats_by_hour[hour]
            except KeyError:
                LOGGER.error(
                    "Did not find photovoltaic data for %s between %02d:00 and %02d:00."
                    " %s (%s) statistics for this time will be missing!",
                    date.isoformat(),
                    hour,
                    hour + 1,
                    self.name_suffix,
                    self.id_suffix,
                )
                continue
            try:
                datapoints_current_hour = [
                    self.calculate_datapoint(*args)
                    for args in zip_measurements(consumptions, pv_stats)
                ]
            except ValueError as exc:
                LOGGER.error(
                    "Failed matching individual electricity of %s and quarter"
                    " photovoltaic data while calculating %s data: %s."
                    " Calculating statistics for the current hour using mean values...",
                    area.name,
                    self.id_suffix,
                    exc,
                )

                aggregate_start = consumption_by_hour[hour][0].start.replace(minute=0)
                aggregate_period = dt.timedelta(hours=1)

                aggregate_consumption = Consumption(
                    start=aggregate_start,
                    period=aggregate_period,
                    value=sum(cons.value for cons in consumptions),
                    unit=all_the_same(cons.unit for cons in consumptions),
                )
                aggregate_pv = PhotovoltaicSummary(
                    start=aggregate_start,
                    period=aggregate_period,
                    consumption=Quantity(
                        value=sum(pv.consumption.value for pv in pv_stats),
                        unit=all_the_same(pv.consumption.unit for pv in pv_stats),
                    ),
                    generation=Quantity(
                        value=sum(pv.generation.value for pv in pv_stats),
                        unit=all_the_same(pv.generation.unit for pv in pv_stats),
                    ),
                    own_consumption=Quantity(
                        value=mean(
                            pv.own_consumption.value
                            if pv.own_consumption is not None
                            else 100.0
                            for pv in pv_stats
                        ),
                        unit=all_the_same(
                            pv.own_consumption.unit
                            for pv in pv_stats
                            if pv is not None and pv.own_consumption is not None
                        ),
                    ),
                    self_sufficiency=Quantity(
                        value=mean(
                            pv.self_sufficiency.value
                            if pv.self_sufficiency is not None
                            else 100.0
                            for pv in pv_stats
                        ),
                        unit=all_the_same(
                            pv.self_sufficiency.unit
                            for pv in pv_stats
                            if pv is not None and pv.self_sufficiency is not None
                        ),
                    ),
                )

                datapoints_current_hour = [
                    self.calculate_datapoint(
                        aggregate_start,
                        aggregate_period,
                        aggregate_consumption,
                        aggregate_pv,
                    )
                ]

            datapoints += datapoints_current_hour

        return datapoints


class IndividualSupplyFromPhotovoltaic(IndividualCalculatedMetric):
    @override
    @property
    def id_suffix(self) -> str:
        return "supply_from_pv"

    @override
    @property
    def name_suffix(self) -> str:
        return "PV-Eigenverbrauch"

    @override
    def calculate_datapoint(
        self,
        start: dt.datetime,
        period: dt.timedelta,
        electricity_consumption: Consumption,
        pv: PhotovoltaicSummary,
    ) -> Datapoint:
        if pv.self_sufficiency is None:
            pv_supply_ratio = 0.0
        else:
            assert pv.self_sufficiency.unit == "%", (  # noqa: S101
                "own_consumption must be measured in %"
            )
            pv_supply_ratio = pv.self_sufficiency.value / 100.0

        # Since self-sufficiency might not always be 0 but contain small deviations, we
        # need to apply a bit of reasonable rounding:
        value = round(electricity_consumption.value * pv_supply_ratio, 3)

        return Datapoint(
            start=start,
            period=period,
            value=value,
            unit=electricity_consumption.unit,
        )


class IndividualSupplyFromGrid(IndividualCalculatedMetric):
    @override
    @property
    def id_suffix(self) -> str:
        return "supply_from_grid"

    @override
    @property
    def name_suffix(self) -> str:
        return "Netzbezug"

    @override
    def calculate_datapoint(
        self,
        start: dt.datetime,
        period: dt.timedelta,
        electricity_consumption: Consumption,
        pv: PhotovoltaicSummary,
    ) -> Datapoint:
        if pv.self_sufficiency is None:
            pv_supply_ratio = 0.0
        else:
            assert pv.self_sufficiency.unit == "%", (  # noqa: S101
                "own_consumption must be measured in %"
            )
            pv_supply_ratio = pv.self_sufficiency.value / 100.0

        # Since self-sufficiency might not always be 0 but contain small deviations, we
        # need to apply a bit of reasonable rounding:
        value = round(electricity_consumption.value * (1 - pv_supply_ratio), 3)
        return Datapoint(
            start=start,
            period=period,
            value=value,
            unit=electricity_consumption.unit,
        )
