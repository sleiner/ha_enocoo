"""Custom types for enocoo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration
    from oocone import Enocoo, model

    from .coordinator import EnocooUpdateCoordinator

    type DailyConsumptionForArea = dict[model.ConsumptionType, model.Consumption | None]
    type DailyConsumption = dict[model.Area, DailyConsumptionForArea]

type EnocooConfigEntry = ConfigEntry[EnocooRuntimeData]


@dataclass
class EnocooRuntimeData:
    """Data for the enocoo integration."""

    client: Enocoo
    coordinator: EnocooUpdateCoordinator
    integration: Integration


@dataclass
class EnocooDashboardData:
    """Data read from the enocoo dashboard."""

    traffic_light_status: model.TrafficLightStatus
    meter_table: list[model.MeterStatus]
    current_photovoltaic_data: model.PhotovoltaicSummary | None
    current_individual_consumption: DailyConsumption
