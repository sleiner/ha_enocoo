"""Sensor entities for quarter-wide data (as well as per ownership shares)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME, PERCENTAGE, UnitOfPower
from homeassistant.helpers.device_registry import DeviceInfo
from oocone.model import Quantity

from .._util import all_the_same
from ..const import (
    ATTR_MEASUREMENT_DURATION,
    ATTR_MEASUREMENT_END,
    ATTR_MEASUREMENT_START,
    CONF_NUM_SHARES,
    CONF_NUM_SHARES_TOTAL,
    SUBENTRY_TYPE_OWNERSHIP_SHARES,
)
from ..entity import EnocooEntity

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from oocone.model import PhotovoltaicSummary

    from ..coordinator import EnocooUpdateCoordinator
    from ..data import EnocooConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: EnocooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities(
        [
            QuarterEnergyProductionEntity(entry.runtime_data.coordinator),
            QuarterEnergyConsumptionEntity(entry.runtime_data.coordinator),
            QuarterPowerSurplusEntity(entry.runtime_data.coordinator),
            QuarterEnergySelfSufficiencyEntity(entry.runtime_data.coordinator),
            QuarterEnergyOwnConsumptionEntity(entry.runtime_data.coordinator),
        ]
    )
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == SUBENTRY_TYPE_OWNERSHIP_SHARES:
            async_add_entities(
                [
                    PerSharePowerSurplusEntity(
                        entry.runtime_data.coordinator,
                        share_name=subentry.data[CONF_NAME],
                        num_shares=subentry.data[CONF_NUM_SHARES],
                        num_shares_total=subentry.data[CONF_NUM_SHARES_TOTAL],
                    )
                ],
                config_subentry_id=subentry_id,
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

    def _get_reading(self, summary: PhotovoltaicSummary) -> Quantity | None:
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
                ATTR_MEASUREMENT_START: pv_data.start,
                ATTR_MEASUREMENT_END: pv_data.start + pv_data.period,
                ATTR_MEASUREMENT_DURATION: str(pv_data.period),
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


class QuarterPowerSurplusEntity(_QuarterEnergyPowerEntity):
    """
    Power being fed into the grid.

    If the quarter receives energy from the grid, this value will not be negative but
    remain zero.
    """

    def __init__(self, coordinator: EnocooUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(
            name_in_dashboard="Quarter power surplus",
            key="quarter_power_surplus",
            coordinator=coordinator,
            icon="mdi:transmission-tower-import",
        )

    @staticmethod
    @override
    def _get_reading(summary: PhotovoltaicSummary) -> Quantity | None:
        return Quantity(
            value=max(summary.generation.value - summary.consumption.value, 0),
            unit=all_the_same([summary.generation.unit, summary.consumption.unit]),
        )


class PerSharePowerSurplusEntity(_QuarterEnergyPowerEntity):
    """Like quarter supply from grid, but scaled for a specific share."""

    def __init__(
        self,
        coordinator: EnocooUpdateCoordinator,
        *,
        share_name: str,
        num_shares: int,
        num_shares_total: int,
    ) -> None:
        """Initialize."""
        super().__init__(
            name_in_dashboard=f"{share_name} power surplus",
            key="per_share_power_surplus",
            coordinator=coordinator,
            icon="mdi:transmission-tower-import",
        )
        self._attr_translation_placeholders = {"share_name": share_name}
        self._num_shares = num_shares
        self._num_shares_total = num_shares_total

    @override
    def _get_reading(self, summary: PhotovoltaicSummary) -> Quantity | None:
        if quarter_surplus := QuarterPowerSurplusEntity._get_reading(summary):  # noqa: SLF001
            return Quantity(
                value=quarter_surplus.value * self._num_shares / self._num_shares_total,
                unit=quarter_surplus.unit,
            )
        return None

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any]:
        return {
            **super().extra_state_attributes,
            "shares": self._num_shares,
            "shares_total": self._num_shares_total,
        }


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
