"""Config flow for the B&D Garage integration."""

from collections.abc import Mapping
import logging
from typing import Any, override

from bnd_garage_client import Credentials, pair_new_phone
from bnd_garage_client.errors import AuthenticationError, HubUnreachableError
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACTIVATION_CODE,
    CONF_DEVICE_IDS,
    CONF_HUB_ID,
    CONF_PHONE_ID,
    CONF_PHONE_PASSWORD,
    CONF_PHONE_SECRET,
    CONF_USER_PASSWORD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_ACTIVATION_CODE): str,
        vol.Required(CONF_USER_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACTIVATION_CODE): str,
        vol.Required(CONF_USER_PASSWORD): str,
    }
)


def _credentials_to_entry_data(
    host: str, credentials: Credentials
) -> dict[str, str | list[str]]:
    return {
        CONF_HOST: host,
        CONF_HUB_ID: credentials.hub_id,
        CONF_PHONE_ID: credentials.phone_id,
        CONF_PHONE_PASSWORD: credentials.phone_password,
        CONF_PHONE_SECRET: credentials.control_secret,
        CONF_USER_PASSWORD: credentials.user_password,
        CONF_DEVICE_IDS: list(credentials.devices),
    }


class BndGarageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for B&D Garage."""

    VERSION = 2

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle pairing a new hub."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                credentials = await pair_new_phone(
                    async_get_clientsession(self.hass),
                    user_input[CONF_HOST],
                    user_input[CONF_ACTIVATION_CODE],
                    user_input[CONF_USER_PASSWORD],
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except HubUnreachableError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during pairing")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(credentials.hub_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="B&D Garage",
                    data=_credentials_to_entry_data(user_input[CONF_HOST], credentials),
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-pairing when the hub rejects stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-pairing."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                credentials = await pair_new_phone(
                    async_get_clientsession(self.hass),
                    reauth_entry.data[CONF_HOST],
                    user_input[CONF_ACTIVATION_CODE],
                    user_input[CONF_USER_PASSWORD],
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except HubUnreachableError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during re-pairing")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(credentials.hub_id)
                self._abort_if_unique_id_mismatch(reason="wrong_hub")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data=_credentials_to_entry_data(
                        reauth_entry.data[CONF_HOST], credentials
                    ),
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )
