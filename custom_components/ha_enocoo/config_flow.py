"""Adds config flow for Blueprint."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util
from oocone import Auth, Enocoo, errors

from .const import DOMAIN, LOGGER


class EnocooFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Enocoo."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        _errors: dict[str, str] = {}
        if user_input is not None:
            self._entry_data = user_input
            if config_entry := await self._async_finalize(_errors):
                return config_entry

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_URL,
                        default=(user_input or {}).get(CONF_URL, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def _async_finalize(
        self, _errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult | None:
        try:
            await self._test_credentials(
                base_url=self._entry_data[CONF_URL],
                username=self._entry_data[CONF_USERNAME],
                password=self._entry_data[CONF_PASSWORD],
            )
        except errors.AuthenticationFailed as exception:
            LOGGER.warning(exception)
            _errors["base"] = "auth"
            return None
        except errors.ConnectionIssue as exception:
            LOGGER.error(exception)
            _errors["base"] = "connection"
            return None
        except errors.OoconeError as exception:
            LOGGER.exception(exception)
            _errors["base"] = "unknown"
            return None
        else:
            return self._async_create_entry()

    def _async_create_entry(self) -> config_entries.ConfigFlowResult:
        if self.source == config_entries.SOURCE_REAUTH:
            existing_entry = self._get_reauth_entry()
        else:
            existing_entry = None

        if existing_entry:
            return self.async_update_reload_and_abort(
                existing_entry, data=self._entry_data
            )

        return self.async_create_entry(
            title=self._entry_data[CONF_USERNAME],
            data=self._entry_data,
        )

    async def _test_credentials(
        self, base_url: str, username: str, password: str
    ) -> None:
        """Validate credentials."""
        client = Enocoo(
            Auth(
                base_url=base_url,
                username=username,
                password=password,
                websession=async_create_clientsession(self.hass),
            ),
            timezone=dt_util.get_default_time_zone(),
        )
        await client.get_meter_table()

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle authentication failures from enocoo dashboard."""
        self._entry_data = entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Provide users the possibility of updating their password."""
        _errors: dict[str, str] = {}
        if user_input is not None:
            self._entry_data.update(**user_input)
            if config_entry := await self._async_finalize(_errors):
                return config_entry

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={
                CONF_URL: self._entry_data[CONF_URL],
                CONF_USERNAME: self._entry_data[CONF_USERNAME],
            },
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=_errors,
        )
