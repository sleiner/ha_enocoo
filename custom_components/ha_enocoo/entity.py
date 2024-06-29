"""BlueprintEntity class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import EnocooDashboardData, EnocooUpdateCoordinator


class EnocooEntity(CoordinatorEntity[EnocooUpdateCoordinator]):
    """Base class for all entities created by the enocoo integration."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: EnocooUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    coordinator.config_entry.entry_id,
                ),
            },
            manufacturer="enocoo",
        )

    @property
    def dashboard_data(self) -> EnocooDashboardData:
        """Returns the data available from the enocoo dashboard."""
        return self.coordinator.data
