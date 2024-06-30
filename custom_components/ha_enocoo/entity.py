"""BlueprintEntity class."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import EnocooDashboardData, EnocooUpdateCoordinator


class EnocooEntity(CoordinatorEntity[EnocooUpdateCoordinator]):
    """Base class for all entities created by the enocoo integration."""

    _attr_has_entity_name = True

    def __init__(self, entity_id: str, coordinator: EnocooUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.entry_id + "_" + entity_id

    @property
    def dashboard_data(self) -> EnocooDashboardData:
        """Returns the data available from the enocoo dashboard."""
        return self.coordinator.data
