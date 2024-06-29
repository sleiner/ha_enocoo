"""Custom types for enocoo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import oocone
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .coordinator import EnocooUpdateCoordinator


type EnocooConfigEntry = ConfigEntry[EnocooRuntimeData]


@dataclass
class EnocooRuntimeData:
    """Data for the enocoo integration."""

    client: oocone.Enocoo
    coordinator: EnocooUpdateCoordinator
    integration: Integration


@dataclass
class EnocooDashboardData:
    """Data read from the enocoo dashboard."""

    traffic_light_status: oocone.types.TrafficLightStatus
