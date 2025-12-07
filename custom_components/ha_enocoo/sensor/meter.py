"""Sensor entities for utility meters."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import ATTR_ENOCOO_AREA, ATTR_READOUT_TIME
from ..entity import EnocooEntity

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from oocone.model import MeterStatus

    from ..coordinator import EnocooUpdateCoordinator
    from ..data import EnocooConfigEntry, EnocooDashboardData


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: EnocooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all entities defined in this module."""
    dashboard_data: EnocooDashboardData = entry.runtime_data.coordinator.data
    async_add_entities(
        [
            MeterEntity.from_meter_status(
                meter_status=status,
                coordinator=entry.runtime_data.coordinator,
            )
            for status in dashboard_data.meter_table
        ]
    )


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
