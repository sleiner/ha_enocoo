"""Sensor platform for enocoo."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from .entity import EnocooEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EnocooUpdateCoordinator
    from .data import EnocooConfigEntry

ENTITY_DESCRIPTIONS = (
    SensorEntityDescription(
        key="energy_traffic_light",
        name="Energy traffic light",
        icon="mdi:traffic-light",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: EnocooConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities(
        IntegrationBlueprintSensor(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class IntegrationBlueprintSensor(EnocooEntity, SensorEntity):
    """enocoo Sensor class."""

    def __init__(
        self,
        coordinator: EnocooUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self.translation_key = "traffic_light"

    @property
    def native_value(self) -> str | None:
        """Return the native value of the sensor."""
        return str(self.dashboard_data.traffic_light_status.color)
