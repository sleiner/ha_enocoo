"""Sensor platform for enocoo."""

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
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.helpers.device_registry import DeviceInfo
from oocone.model import Quantity, UnknownT

from custom_components.ha_enocoo.const import ATTR_ENOCOO_AREA, ATTR_READOUT_TIME

from .entity import EnocooEntity

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from oocone.model import MeterStatus, PhotovoltaicSummary

    from custom_components.ha_enocoo.data import EnocooDashboardData

    from .coordinator import EnocooUpdateCoordinator
    from .data import EnocooConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: EnocooConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    dashboard_data: EnocooDashboardData = entry.runtime_data.coordinator.data
    async_add_entities(
        [
            EnergyTrafficLightColorEntity(
                coordinator=entry.runtime_data.coordinator,
                entity_description=SensorEntityDescription(
                    key="energy_traffic_light",
                    name="Energy traffic light",
                    icon="mdi:traffic-light",
                    device_class=SensorDeviceClass.ENUM,
                ),
            ),
            EnergyTrafficLightPriceEntity(
                coordinator=entry.runtime_data.coordinator,
                entity_description=SensorEntityDescription(
                    key="calculated_electricity_price",
                    name="Calculated electricity price",
                    icon="mdi:currency-eur",
                    device_class=SensorDeviceClass.MONETARY,
                    suggested_display_precision=2,
                ),
            ),
            QuarterEnergyProductionEntity(entry.runtime_data.coordinator),
            QuarterEnergyConsumptionEntity(entry.runtime_data.coordinator),
            QuarterEnergySelfSufficiencyEntity(entry.runtime_data.coordinator),
            QuarterEnergyOwnConsumptionEntity(entry.runtime_data.coordinator),
        ]
        + [
            MeterEntity.from_meter_status(
                meter_status=status,
                coordinator=entry.runtime_data.coordinator,
            )
            for status in dashboard_data.meter_table
        ]
    )


class EnergyTrafficLightEntity(EnocooEntity, SensorEntity):
    """Energy traffic light."""

    def __init__(
        self,
        coordinator: EnocooUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor class."""
        super().__init__(entity_id=entity_description.key, coordinator=coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    coordinator.config_entry.entry_id,
                ),
            },
            manufacturer="enocoo",
        )

        self.entity_description = entity_description
        self.translation_key = entity_description.key


class EnergyTrafficLightColorEntity(EnergyTrafficLightEntity):
    """Color of the energy traffic light."""

    @override
    @property
    def native_value(self) -> str | None:
        return str(self.dashboard_data.traffic_light_status.color)


class EnergyTrafficLightPriceEntity(EnergyTrafficLightEntity):
    """Energy price indicated by the traffic light."""

    def _normalized_price(self) -> Quantity | UnknownT:
        price = self.dashboard_data.traffic_light_status.current_energy_price

        if price != "UNKNOWN" and price.unit == "ct/kWh":
            price = Quantity(value=price.value / 100.0, unit="€/kWh")

        return price

    @override
    @property
    def native_value(self) -> float | None:
        price = self._normalized_price()
        if price == "UNKNOWN":
            return None
        return price.value

    @override
    @property
    def native_unit_of_measurement(self) -> str | None:
        price = self._normalized_price()
        if price == "UNKNOWN":
            return None
        return price.unit


class MeterEntity(EnocooEntity, SensorEntity):
    """Entity for utility meters."""

    def __init__(
        self,
        meter_id: str,
        name_in_dashboard: str,
        coordinator: EnocooUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(entity_id=name_in_dashboard, coordinator=coordinator)
        self.meter_id = meter_id
        self.name_in_dashboard = name_in_dashboard
        self.entity_description = entity_description
        self.translation_key = "meter"

        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    name_in_dashboard,
                ),
            },
            serial_number=meter_id,
            name=f"Meter #{meter_id}",
            translation_key="meter_with_id",
            translation_placeholders={"meter_id": meter_id},
        )

    @staticmethod
    def from_meter_status(
        meter_status: MeterStatus,
        coordinator: EnocooUpdateCoordinator,
    ) -> MeterEntity:
        """Create a MeterEntity from a MeterStatus instance returned by oocone."""
        description = SensorEntityDescription(
            key=meter_status.name,
            name=meter_status.name.replace(f" {meter_status.area}", ""),
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:meter-electric",
        )
        if " Kaltwasser " in meter_status.name or " Warmwasser " in meter_status.name:
            description = replace(description, device_class=SensorDeviceClass.WATER)
        elif " Strom " in meter_status.name:
            description = replace(description, device_class=SensorDeviceClass.ENERGY)
        elif " Wärme " in meter_status.name:
            description = replace(
                description,
                device_class=SensorDeviceClass.ENERGY,
                icon="mdi:meter-gas",
            )

        return MeterEntity(
            meter_id=meter_status.meter_id,
            name_in_dashboard=meter_status.name,
            coordinator=coordinator,
            entity_description=description,
        )

    @property
    @override
    def native_unit_of_measurement(self) -> str:
        return self._current_meter_status().reading.unit

    @property
    @override
    def native_value(self) -> float | None:
        """Return the native value of the sensor."""
        return self._current_meter_status().reading.value

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any]:
        meter_status = self._current_meter_status()

        return {
            ATTR_ENOCOO_AREA: meter_status.area,
            ATTR_READOUT_TIME: meter_status.timestamp,
        }

    def _current_meter_status(self) -> MeterStatus:
        return next(
            meter
            for meter in self.dashboard_data.meter_table
            if meter.meter_id == self.meter_id and meter.name == self.name_in_dashboard
        )


class _QuarterEnergyEntity(EnocooEntity, SensorEntity):
    def __init__(
        self,
        name_in_dashboard: str,
        translation_key: str,
        coordinator: EnocooUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        super().__init__(entity_id=name_in_dashboard, coordinator=coordinator)
        self.entity_description = entity_description
        self.translation_key = translation_key

        self._attr_device_info = DeviceInfo(
            identifiers={(coordinator.config_entry.entry_id, "quarter_photovoltaic")},
            name="Quarter energy",
            translation_key="quarter_energy",
        )

    @property
    def _pv_data(self) -> PhotovoltaicSummary | None:
        return self.dashboard_data.current_photovoltaic_data

    @staticmethod
    def _get_reading(summary: PhotovoltaicSummary) -> Quantity | None:
        """Return the specific reading relevant for the current sensor."""
        raise NotImplementedError

    @property
    @override
    def native_value(self) -> float | None:
        if pv_data := self._pv_data:  # noqa: SIM102
            if reading := self._get_reading(pv_data):
                return reading.value

        return None

    @property
    @override
    def native_unit_of_measurement(self) -> str | None:
        if pv_data := self._pv_data:  # noqa: SIM102
            if reading := self._get_reading(pv_data):
                return reading.unit

        return None

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any]:
        if pv_data := self._pv_data:
            return {
                ATTR_READOUT_TIME: pv_data.start + pv_data.period,
            }

        return {}


class _QuarterEnergyPowerEntity(_QuarterEnergyEntity):
    def __init__(
        self,
        name_in_dashboard: str,
        key: str,
        coordinator: EnocooUpdateCoordinator,
        icon: str | None = None,
    ) -> None:
        super().__init__(
            name_in_dashboard=name_in_dashboard,
            translation_key=key,
            coordinator=coordinator,
            entity_description=SensorEntityDescription(
                key=key,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
                icon=icon,
            ),
        )

    @property
    @override
    def native_unit_of_measurement(self) -> str:
        return UnitOfPower.KILO_WATT

    @property
    @override
    def native_value(self) -> float | None:
        if pv_data := self._pv_data:  # noqa: SIM102
            if reading := self._get_reading(pv_data):  # noqa: SIM102
                if reading.unit == "kWh":
                    return reading.value * (dt.timedelta(hours=1) / pv_data.period)

        return None


class QuarterEnergyProductionEntity(_QuarterEnergyPowerEntity):
    """Quarter energy from PV power plant."""

    def __init__(self, coordinator: EnocooUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(
            name_in_dashboard="Quarter energy production",
            key="quarter_energy_production",
            coordinator=coordinator,
            icon="mdi:solar-power-variant",
        )

    @staticmethod
    @override
    def _get_reading(summary: PhotovoltaicSummary) -> Quantity:
        return summary.generation


class QuarterEnergyConsumptionEntity(_QuarterEnergyPowerEntity):
    """Overall energy consumption of the quarter."""

    def __init__(self, coordinator: EnocooUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(
            name_in_dashboard="Quarter energy consumption",
            key="quarter_energy_consumption",
            coordinator=coordinator,
            icon="mdi:home-lightning-bolt-outline",
        )

    @staticmethod
    @override
    def _get_reading(summary: PhotovoltaicSummary) -> Quantity:
        return summary.consumption


class _QuarterEnergyPercentageEntity(_QuarterEnergyEntity):
    def __init__(
        self,
        name_in_dashboard: str,
        key: str,
        coordinator: EnocooUpdateCoordinator,
        icon: str | None = None,
    ) -> None:
        super().__init__(
            name_in_dashboard=name_in_dashboard,
            translation_key=key,
            coordinator=coordinator,
            entity_description=SensorEntityDescription(
                key=key,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=PERCENTAGE,
                suggested_display_precision=1,
                icon=icon,
            ),
        )


class QuarterEnergySelfSufficiencyEntity(_QuarterEnergyPercentageEntity):
    """Current self-sufficiency of the quarter from the electrical grid."""

    def __init__(self, coordinator: EnocooUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(
            name_in_dashboard="Self-sufficiency",
            key="self_sufficiency",
            coordinator=coordinator,
            icon="mdi:transmission-tower-import",
        )

    @staticmethod
    @override
    def _get_reading(summary: PhotovoltaicSummary) -> Quantity | None:
        return summary.self_sufficiency


class QuarterEnergyOwnConsumptionEntity(_QuarterEnergyPercentageEntity):
    """Current degree of own consumption of the quarter's PV power plant."""

    def __init__(self, coordinator: EnocooUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(
            name_in_dashboard="Own consumption",
            key="own_consumption",
            coordinator=coordinator,
            icon="mdi:transmission-tower-export",
        )

    @staticmethod
    @override
    def _get_reading(summary: PhotovoltaicSummary) -> Quantity | None:
        return summary.own_consumption
