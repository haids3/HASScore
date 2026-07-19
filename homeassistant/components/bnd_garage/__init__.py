"""The B&D Garage integration."""

from bnd_garage_client import Credentials, HubClient
from bnd_garage_client.errors import AuthenticationError, HubUnreachableError

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DEVICE_IDS,
    CONF_HUB_ID,
    CONF_PHONE_ID,
    CONF_PHONE_PASSWORD,
    CONF_PHONE_SECRET,
    CONF_USER_PASSWORD,
)
from .coordinator import BndGarageConfigEntry, BndGarageDataUpdateCoordinator

_OLD_CONF_ACTION_DEVICE_ID = "action_device_id"
"""The single-device config entry key this integration used before multiple
devices per hub were supported - kept only for `async_migrate_entry`."""

_PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: BndGarageConfigEntry) -> bool:
    """Set up B&D Garage from a config entry.

    One config entry manages every device the hub reports under this
    phone's credentials (a hub with multiple door openers grants control
    over all of them from one pairing) - each gets its own coordinator,
    sharing a single HubClient/session.
    """
    credentials = Credentials(
        hub_id=entry.data[CONF_HUB_ID],
        phone_id=entry.data[CONF_PHONE_ID],
        phone_password=entry.data[CONF_PHONE_PASSWORD],
        control_secret=entry.data[CONF_PHONE_SECRET],
        user_password=entry.data[CONF_USER_PASSWORD],
        devices=tuple(entry.data[CONF_DEVICE_IDS]),
    )
    client = HubClient(entry.data[CONF_HOST], credentials)

    try:
        await client.connect()
    except AuthenticationError as err:
        await client.close()
        raise ConfigEntryAuthFailed from err
    except HubUnreachableError as err:
        await client.close()
        raise ConfigEntryNotReady from err

    coordinators = [
        BndGarageDataUpdateCoordinator(hass, entry, client, device_id)
        for device_id in credentials.devices
    ]
    for coordinator in coordinators:
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BndGarageConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
        await entry.runtime_data[0].client.close()

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: BndGarageConfigEntry) -> bool:
    """Migrate a pre-multi-device config entry to the device-list schema.

    Older entries store one device ID under `action_device_id` and every
    entity's unique_id is a bare hub_id - multi-device support keys entries
    by `device_ids` and scopes each entity's unique_id to `hub_id_device_id`,
    so both need rewriting in place for existing installs to keep their
    entity history/automations instead of getting orphaned duplicates.
    """
    if entry.version > 1:
        return True

    old_device_id = entry.data.get(_OLD_CONF_ACTION_DEVICE_ID)
    if old_device_id is None:
        return True

    new_data = {k: v for k, v in entry.data.items() if k != _OLD_CONF_ACTION_DEVICE_ID}
    new_data[CONF_DEVICE_IDS] = [old_device_id]
    hass.config_entries.async_update_entry(entry, data=new_data, version=2)

    hub_id = entry.unique_id
    assert hub_id is not None
    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        old_unique_id = entity_entry.unique_id
        if not (old_unique_id == hub_id or old_unique_id.startswith(f"{hub_id}_")):
            continue
        new_unique_id = f"{hub_id}_{old_device_id}" + old_unique_id[len(hub_id) :]
        registry.async_update_entity(
            entity_entry.entity_id, new_unique_id=new_unique_id
        )

    return True
