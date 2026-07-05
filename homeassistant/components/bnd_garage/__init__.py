"""The B&D Garage integration."""

from bnd_garage_api import Client, Credentials
from bnd_garage_api.exceptions import CannotConnect, InvalidAuth

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import (
    CONF_ACTION_DEVICE_ID,
    CONF_HUB_ID,
    CONF_PHONE_ID,
    CONF_PHONE_PASSWORD,
    CONF_PHONE_SECRET,
    CONF_USER_PASSWORD,
)
from .coordinator import BndGarageConfigEntry, BndGarageDataUpdateCoordinator

_PLATFORMS: list[Platform] = [Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: BndGarageConfigEntry) -> bool:
    """Set up B&D Garage from a config entry."""
    credentials = Credentials(
        hub_id=entry.data[CONF_HUB_ID],
        phone_id=entry.data[CONF_PHONE_ID],
        phone_password=entry.data[CONF_PHONE_PASSWORD],
        phone_secret=entry.data[CONF_PHONE_SECRET],
        user_password=entry.data[CONF_USER_PASSWORD],
        action_device_id=entry.data[CONF_ACTION_DEVICE_ID],
    )
    client = Client(entry.data[CONF_HOST], credentials)

    try:
        await client.async_connect()
    except InvalidAuth as err:
        await client.async_close()
        raise ConfigEntryAuthFailed from err
    except CannotConnect as err:
        await client.async_close()
        raise ConfigEntryNotReady from err

    coordinator = BndGarageDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BndGarageConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
        await entry.runtime_data.client.async_close()

    return unload_ok
