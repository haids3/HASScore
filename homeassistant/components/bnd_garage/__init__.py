"""The B&D Garage integration."""

from datetime import datetime, timedelta

from bnd_garage_client import Credentials, HubClient
from bnd_garage_client.errors import AuthenticationError, HubUnreachableError

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_DEVICE_IDS,
    CONF_HUB_ID,
    CONF_PHONE_ID,
    CONF_PHONE_PASSWORD,
    CONF_PHONE_SECRET,
    CONF_USER_PASSWORD,
    DOMAIN,
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

_DEVICE_DISCOVERY_INTERVAL = timedelta(minutes=30)


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

    await _async_update_title_from_hub_info(hass, entry, client)

    coordinators = [
        BndGarageDataUpdateCoordinator(hass, entry, client, device_id)
        for device_id in credentials.devices
    ]
    for coordinator in coordinators:
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    async def _check_for_new_devices(_now: datetime) -> None:
        """Reload the entry if the hub now reports a device we don't have.

        Devices are only ever added here, never removed - if the hub stops
        reporting one, its entities simply go unavailable rather than being
        torn down, matching how a temporarily-unreachable device behaves.
        """
        try:
            current_ids = await client.get_device_ids()
        except AuthenticationError, HubUnreachableError:
            return
        known_ids = set(entry.data[CONF_DEVICE_IDS])
        if not set(current_ids) - known_ids:
            return
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_DEVICE_IDS: list(current_ids)}
        )
        await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(
        async_track_time_interval(
            hass, _check_for_new_devices, _DEVICE_DISCOVERY_INTERVAL
        )
    )

    return True


async def _async_update_title_from_hub_info(
    hass: HomeAssistant, entry: BndGarageConfigEntry, client: HubClient
) -> None:
    """Rename the config entry to the hub's own configured name, if available.

    Cosmetic only - never blocks setup if the hub doesn't support this call
    or reports an empty name.
    """
    try:
        hub_info = await client.get_hub_info()
    except AuthenticationError, HubUnreachableError:
        return
    if hub_info is not None and hub_info.name and hub_info.name != entry.title:
        hass.config_entries.async_update_entry(entry, title=hub_info.name)


async def async_unload_entry(hass: HomeAssistant, entry: BndGarageConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
        await entry.runtime_data[0].client.close()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: BndGarageConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device the hub no longer reports.

    Home Assistant refuses to let a device tied to a live config entry be
    deleted from the UI unless the integration explicitly permits it here.
    Only orphaned devices - e.g. left behind by the pre-multi-device
    migration, or a door genuinely removed from the hub - are approved; a
    device matching a currently-known device ID is refused, so an active
    door can't be deleted out from under a live config entry.
    """
    hub_id = entry.unique_id
    known_keys = {f"{hub_id}_{device_id}" for device_id in entry.data[CONF_DEVICE_IDS]}
    return not any(
        domain == DOMAIN and key in known_keys
        for domain, key in device_entry.identifiers
    )


async def async_migrate_entry(hass: HomeAssistant, entry: BndGarageConfigEntry) -> bool:
    """Migrate a pre-multi-device config entry to the device-list schema.

    Older entries store one device ID under `action_device_id`, every
    entity's unique_id is a bare hub_id, and the HA device entry is
    identified by a bare hub_id too - multi-device support keys entries by
    `device_ids` and scopes both the unique_id and the device identifier to
    `hub_id_device_id`, so all three need rewriting in place for existing
    installs to keep their entity/device history and automations instead of
    getting orphaned duplicates.
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
    new_device_key = f"{hub_id}_{old_device_id}"

    device_registry = dr.async_get(hass)
    old_device = device_registry.async_get_device(identifiers={(DOMAIN, hub_id)})
    if old_device is not None:
        device_registry.async_update_device(
            old_device.id, new_identifiers={(DOMAIN, new_device_key)}
        )

    entity_registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        old_unique_id = entity_entry.unique_id
        if not (old_unique_id == hub_id or old_unique_id.startswith(f"{hub_id}_")):
            continue
        new_unique_id = new_device_key + old_unique_id[len(hub_id) :]
        entity_registry.async_update_entity(
            entity_entry.entity_id, new_unique_id=new_unique_id
        )

    return True
