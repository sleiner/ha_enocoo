"""Sensor entities for (individual) consumption."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import TYPE_CHECKING, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.helpers.device_registry import DeviceInfo
from oocone.model import Consumption, ConsumptionType

from .._pv_metrics import IndividualCalculatedMetric
from .._util import relevant_consumption_types
from ..const import (
    ATTR_ENOCOO_AREA,
    ATTR_MEASUREMENT_DURATION,
    ATTR_MEASUREMENT_END,
    ATTR_MEASUREMENT_START,
)
from ..entity import EnocooEntity

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from oocone.model import Area, Consumption

    from ..coordinator import EnocooUpdateCoordinator
    from ..data import EnocooConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: EnocooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all entities defined in this module."""
    enocoo = entry.runtime_data.coordinator.enocoo
    entities: list[_BaseConsumptionEntity] = []
    for area in await enocoo.get_areas():
        for consumption_type in relevant_consumption_types(area):
            entities.append(
                MeasuredConsumptionEntity(
                    area,
                    consumption_type,
                    coordinator=entry.runtime_data.coordinator,
                ),
            )
            if consumption_type == ConsumptionType.ELECTRICITY:
                entities.extend(
                    CalculatedElectricityConsumptionEntity(
                        area,
                        consumption_type,
                        calculation,
                        coordinator=entry.runtime_data.coordinator,
                    )
                    for calculation in IndividualCalculatedMetric.metrics
                )
    async_add_entities(entities)


class _BaseConsumptionEntity(EnocooEntity, SensorEntity):
    def __init__(  # noqa: PLR0913
        self,
        id_segment: str,
        name_in_dashboard: str,
        icon: str,
        area: Area,
        consumption_type: ConsumptionType,
        coordinator: EnocooUpdateCoordinator,
    ) -> None:
        """Initialize."""
        entity_id = f"{id_segment}_flow".lower()
        super().__init__(entity_id=entity_id, coordinator=coordinator)
        self.entity_description = SensorEntityDescription(
            key=entity_id,
            name=name_in_dashboard,
            translation_key=entity_id,
            state_class=SensorStateClass.MEASUREMENT,
            device_class=_device_class(consumption_type),
            icon=icon,
        )

        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.entry_id,
                    f"entity-type=consumption,area={area.id}",
                ),
            },
            name=f"Consumption for {area.name}",
            translation_key="consumption",
            translation_placeholders={"area_name": area.name},
        )
        self._area = area
        self._consumption_type = consumption_type

    @property
    @override
    def native_unit_of_measurement(self) -> str | None:
        result: str | None = None
        if consumption := self._current_consumption():
            integrated_unit = consumption.unit
            match integrated_unit:
                case UnitOfEnergy.KILO_WATT_HOUR:
                    result = UnitOfPower.KILO_WATT
                case UnitOfVolume.CUBIC_METERS:
                    result = UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR
                case _:
                    msg = f"Unexpected type of consumption unit: {integrated_unit}"
                    raise NotImplementedError(msg)
        return result

    @property
    @override
    def native_value(self) -> float | None:
        """Return the native value of the sensor."""
        if consumption := self._current_consumption():
            result = self.calculate_value(consumption)
        else:
            result = None
        return result

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any]:
        consumption = self._current_consumption()

        result: dict[str, Any] = {
            ATTR_ENOCOO_AREA: self._area.name,
        }

        if consumption := self._current_consumption():
            result[ATTR_MEASUREMENT_START] = consumption.start
            result[ATTR_MEASUREMENT_END] = consumption.start + consumption.period
            result[ATTR_MEASUREMENT_DURATION] = str(consumption.period)

        return result

    def _current_consumption(self) -> Consumption | None:
        return self.dashboard_data.current_individual_consumption[self._area.id][
            self._consumption_type
        ]

    def calculate_value(self, consumption: Consumption) -> float:
        # "consumption" gives us a summarized reading over a period.
        # We want to provide "current" values for the period (e.g. power instead of
        # energy, volume flow instead of volume etc.).
        return consumption.value * (dt.timedelta(hours=1) / consumption.period)


class MeasuredConsumptionEntity(_BaseConsumptionEntity):
    """A consumption measurement fetched directly from the enocoo dashboard."""

    def __init__(
        self,
        area: Area,
        consumption_type: ConsumptionType,
        coordinator: EnocooUpdateCoordinator,
    ) -> None:
        """Initialize."""
        super().__init__(
            id_segment=consumption_type,
            name_in_dashboard=f"{consumption_type.title()} flow",
            icon=MeasuredConsumptionEntity.__get_icon(consumption_type),
            area=area,
            consumption_type=consumption_type,
            coordinator=coordinator,
        )

    @staticmethod
    def __get_icon(consumption_type: ConsumptionType) -> str:
        match consumption_type:
            case ConsumptionType.ELECTRICITY:
                return "mdi:lightning-bolt"
            case ConsumptionType.HEAT:
                return "mdi:heat-wave"
            case ConsumptionType.WATER_COLD:
                return "mdi:water-outline"
            case ConsumptionType.WATER_HOT:
                return "mdi:water"
            case _:
                return ""


class CalculatedElectricityConsumptionEntity(_BaseConsumptionEntity):
    """A consumption measurement calculated from multiple data sources."""

    def __init__(
        self,
        area: Area,
        consumption_type: ConsumptionType,
        calculation: type[IndividualCalculatedMetric],
        coordinator: EnocooUpdateCoordinator,
    ) -> None:
        """Initialize."""
        super().__init__(
            id_segment=f"electricity_{calculation.id_suffix()}",
            name_in_dashboard=f"{calculation.name_suffix_de()} flow",
            icon=calculation.icon(),
            area=area,
            consumption_type=consumption_type,
            coordinator=coordinator,
        )
        self._calculation = calculation

    @override
    def calculate_value(self, consumption: Consumption) -> float:
        power_cons = replace(
            consumption,
            value=super().calculate_value(consumption),
            unit=self.native_unit_of_measurement or "UNKNOWN",
        )
        pv = self.dashboard_data.current_photovoltaic_data
        if not pv:
            msg = (
                "No PV data are available."
                f" Cannot calculate {self._calculation.id_suffix()}"
            )
            raise ValueError(msg)
        if (power_cons.start != pv.start) or (power_cons.period != pv.period):
            msg = (
                "Measurement periods for PV data and power consumption do not match:"
                f" {pv=}, {power_cons=}"
            )
            raise ValueError(msg)
        dp = self._calculation.calculate_datapoint(
            power_cons.start, power_cons.period, power_cons, pv
        )
        return dp.value


def _device_class(consumption_type: ConsumptionType) -> SensorDeviceClass:
    match consumption_type:
        case ConsumptionType.ELECTRICITY | ConsumptionType.HEAT:
            return SensorDeviceClass.POWER
        case ConsumptionType.WATER_COLD | ConsumptionType.WATER_HOT:
            return SensorDeviceClass.VOLUME_FLOW_RATE

    msg = f"Unknown consumption type: {consumption_type}"
    raise NotImplementedError(msg)
