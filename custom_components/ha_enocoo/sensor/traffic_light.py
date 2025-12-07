"""Sensor entities related to the energy traffic light."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.helpers.device_registry import DeviceInfo
from oocone.model import Quantity, UnknownT

from ..entity import EnocooEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from ..coordinator import EnocooUpdateCoordinator
    from ..data import EnocooConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: EnocooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all entities defined in this module."""
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
        ]
    )


class _EnergyTrafficLightEntity(EnocooEntity, SensorEntity):
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


class EnergyTrafficLightColorEntity(_EnergyTrafficLightEntity):
    """Color of the energy traffic light."""

    @override
    @property
    def native_value(self) -> str | None:
        return str(self.dashboard_data.traffic_light_status.color)


class EnergyTrafficLightPriceEntity(_EnergyTrafficLightEntity):
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
