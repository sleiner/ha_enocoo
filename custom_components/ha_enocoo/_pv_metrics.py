from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from itertools import groupby
from statistics import mean
from typing import TYPE_CHECKING, ClassVar, Self, override

from homeassistant.util.unit_conversion import EnergyConverter
from oocone.model import (
    Area,
    Consumption,
    ConsumptionType,
    PhotovoltaicSummary,
    Quantity,
)

from ._util import all_the_same, zip_measurements
from .const import LOGGER

if TYPE_CHECKING:
    from collections.abc import Sequence

    import oocone


Datapoint = Consumption


class IndividualCalculatedMetric(ABC):
    metrics: ClassVar[list[type[Self]]] = []

    def __init_subclass__(cls) -> None:
        IndividualCalculatedMetric.metrics.append(cls)

    def __init__(self, enocoo: oocone.Enocoo) -> None:
        self.enocoo = enocoo

    @classmethod
    @abstractmethod
    def icon(cls) -> str:
        """Return the icon representing the metric in the UI."""

    @classmethod
    @abstractmethod
    def id_suffix(cls) -> str:
        """Return the suffix for the statistic ID, identifying the metric."""

    @classmethod
    @abstractmethod
    def name_suffix(cls) -> str:
        """Return the suffix for the statistic name, identifying the metric."""

    # Since statistics cannot be translated, and the complete user base resides in
    # Germany, we use the German terminology for the statistics:
    @classmethod
    @abstractmethod
    def name_suffix_de(cls) -> str:
        """Return the suffix for the statistic name, identifying the metric."""

    @classmethod
    @abstractmethod
    def unit_class(cls) -> str:
        """Return the unit class (see homeassistant.util.unit_conversion)."""

    @staticmethod
    @abstractmethod
    def calculate_datapoint(
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
            consumption_type=ConsumptionType.ELECTRICITY,
            area_id=area.id,
            interval="day",
            during=date,
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
                    self.name_suffix_de(),
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
                    self.name_suffix_de(),
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
    @classmethod
    @override
    def icon(cls) -> str:
        return "mdi:solar-power"

    @classmethod
    @override
    def id_suffix(cls) -> str:
        return "supply_from_pv"

    @classmethod
    @override
    def name_suffix(cls) -> str:
        return "Supply from PV"

    @classmethod
    @override
    def name_suffix_de(cls) -> str:
        return "PV-Eigenverbrauch"

    @classmethod
    @override
    def unit_class(cls) -> str:
        return EnergyConverter.UNIT_CLASS

    @override
    @staticmethod
    def calculate_datapoint(
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
    @classmethod
    @override
    def icon(cls) -> str:
        return "mdi:transmission-tower-export"

    @classmethod
    @override
    def id_suffix(cls) -> str:
        return "supply_from_grid"

    @classmethod
    @override
    def name_suffix(cls) -> str:
        return "Supply from grid"

    @classmethod
    @override
    def name_suffix_de(cls) -> str:
        return "Netzbezug"

    @classmethod
    @override
    def unit_class(cls) -> str:
        return EnergyConverter.UNIT_CLASS

    @override
    @staticmethod
    def calculate_datapoint(
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
