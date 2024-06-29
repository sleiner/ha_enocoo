"""DataUpdateCoordinator for enocoo."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import oocone
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER
from .data import EnocooDashboardData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import EnocooConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class EnocooUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: EnocooConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=15),
            always_update=False,
        )

    async def _async_update_data(self) -> EnocooDashboardData:
        """Update data via library."""
        client = self.config_entry.runtime_data.client

        try:
            dashboard_data = EnocooDashboardData(
                traffic_light_status=await client.get_traffic_light_status(),
            )
        except oocone.errors.AuthenticationFailed as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except oocone.errors.OoconeError as exception:
            raise UpdateFailed(exception) from exception

        return dashboard_data
