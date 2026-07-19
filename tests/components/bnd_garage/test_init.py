"""Test the B&D Garage integration setup."""

from unittest.mock import AsyncMock, patch

from bnd_garage_client.errors import AuthenticationError, HubUnreachableError
from bnd_garage_client.models import DoorState, HubInfo, HubStatus
import pytest

from homeassistant.components.bnd_garage import _DEVICE_DISCOVERY_INTERVAL
from homeassistant.components.bnd_garage.const import (
    CONF_DEVICE_IDS,
    CONF_HUB_ID,
    CONF_PHONE_ID,
    CONF_PHONE_PASSWORD,
    CONF_PHONE_SECRET,
    CONF_USER_PASSWORD,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import homeassistant.util.dt as dt_util

from . import setup_integration
from .conftest import TEST_CREDENTIALS, TEST_DEVICE_ID, TEST_HOST, TEST_HUB_ID

from tests.common import MockConfigEntry, async_fire_time_changed


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test setup and unload of the config entry."""
    await setup_integration(hass, mock_config_entry, [])

    assert mock_config_entry.state is ConfigEntryState.LOADED
    mock_client.connect.assert_awaited_once()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.close.assert_awaited_once()


async def test_setup_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test that an auth failure during setup marks the entry as an error."""
    mock_client.connect.side_effect = AuthenticationError
    await setup_integration(hass, mock_config_entry, [])

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    mock_client.close.assert_awaited_once()


async def test_setup_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test that a connection failure during setup schedules a retry."""
    mock_client.connect.side_effect = HubUnreachableError
    await setup_integration(hass, mock_config_entry, [])

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_client.close.assert_awaited_once()


@pytest.mark.usefixtures("mock_client")
async def test_creates_cover_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the cover platform is forwarded and creates an entity."""
    await setup_integration(hass, mock_config_entry, [Platform.COVER])

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert len(entries) == 1
    assert entries[0].domain == "cover"
    assert entries[0].unique_id == f"{TEST_HUB_ID}_{TEST_DEVICE_ID}"

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_creates_one_coordinator_and_entity_set_per_device(
    hass: HomeAssistant,
    mock_client: AsyncMock,
) -> None:
    """Test a hub with multiple doors gets one coordinator/entity set each.

    Reflects the real-world model this integration targets: one pairing's
    credentials grant control over every device the hub reports, not just
    a single door - confirmed against `THE-MAVER1CK/b-and-d-garage-api#2`
    (a real multi-door user) before implementing this.
    """
    device_a, device_b = "device-a", "device-b"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="B&D Garage",
        data={
            CONF_HOST: TEST_HOST,
            CONF_HUB_ID: TEST_HUB_ID,
            CONF_PHONE_ID: TEST_CREDENTIALS.phone_id,
            CONF_PHONE_PASSWORD: TEST_CREDENTIALS.phone_password,
            CONF_PHONE_SECRET: TEST_CREDENTIALS.control_secret,
            CONF_USER_PASSWORD: TEST_CREDENTIALS.user_password,
            CONF_DEVICE_IDS: [device_a, device_b],
        },
        unique_id=TEST_HUB_ID,
    )
    statuses = {
        device_a: HubStatus(
            state=DoorState.CLOSED, position=0, rate=0, name="Front Door"
        ),
        device_b: HubStatus(
            state=DoorState.OPEN, position=100, rate=0, name="Side Door"
        ),
    }
    mock_client.get_status.side_effect = lambda device_id: statuses[device_id]

    await setup_integration(hass, entry, [Platform.COVER])

    assert len(entry.runtime_data) == 2
    assert {coordinator.device_id for coordinator in entry.runtime_data} == {
        device_a,
        device_b,
    }

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {entity_entry.unique_id for entity_entry in entries} == {
        f"{TEST_HUB_ID}_{device_a}",
        f"{TEST_HUB_ID}_{device_b}",
    }

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_migrates_single_device_entry_to_device_list(
    hass: HomeAssistant,
    mock_client: AsyncMock,
) -> None:
    """Test a pre-multi-device entry's data and entity unique_ids get migrated.

    Older entries stored one device under `action_device_id` and a bare
    hub_id as every entity's unique_id - both need rewriting so existing
    installs keep their entity history instead of getting orphaned
    duplicates once a config entry can cover multiple devices.
    """
    old_entry = MockConfigEntry(
        domain=DOMAIN,
        title="B&D Garage",
        version=1,
        data={
            CONF_HOST: TEST_HOST,
            CONF_HUB_ID: TEST_HUB_ID,
            CONF_PHONE_ID: TEST_CREDENTIALS.phone_id,
            CONF_PHONE_PASSWORD: TEST_CREDENTIALS.phone_password,
            CONF_PHONE_SECRET: TEST_CREDENTIALS.control_secret,
            CONF_USER_PASSWORD: TEST_CREDENTIALS.user_password,
            "action_device_id": TEST_DEVICE_ID,
        },
        unique_id=TEST_HUB_ID,
    )
    old_entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=old_entry.entry_id,
        identifiers={(DOMAIN, TEST_HUB_ID)},
        name="B&D Garage",
    )

    entity_registry = er.async_get(hass)
    cover_entry = entity_registry.async_get_or_create(
        "cover", DOMAIN, TEST_HUB_ID, config_entry=old_entry, device_id=old_device.id
    )
    switch_entry = entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{TEST_HUB_ID}_auxiliary",
        config_entry=old_entry,
        device_id=old_device.id,
    )

    with patch("homeassistant.components.bnd_garage._PLATFORMS", []):
        assert await hass.config_entries.async_setup(old_entry.entry_id)
        await hass.async_block_till_done()

    assert old_entry.version == 2
    assert old_entry.data[CONF_DEVICE_IDS] == [TEST_DEVICE_ID]
    assert "action_device_id" not in old_entry.data

    migrated_cover = entity_registry.async_get(cover_entry.entity_id)
    assert migrated_cover is not None
    assert migrated_cover.unique_id == f"{TEST_HUB_ID}_{TEST_DEVICE_ID}"

    migrated_switch = entity_registry.async_get(switch_entry.entity_id)
    assert migrated_switch is not None
    assert migrated_switch.unique_id == f"{TEST_HUB_ID}_{TEST_DEVICE_ID}_auxiliary"

    assert device_registry.async_get_device(identifiers={(DOMAIN, TEST_HUB_ID)}) is None
    migrated_device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{TEST_HUB_ID}_{TEST_DEVICE_ID}")}
    )
    assert migrated_device is not None
    assert migrated_device.id == old_device.id

    assert await hass.config_entries.async_unload(old_entry.entry_id)
    await hass.async_block_till_done()


def _hub_info(name: str) -> HubInfo:
    return HubInfo(
        name=name,
        ap_name="",
        serial_number="",
        version="",
        firmware="",
        timezone="",
        saved_network="",
        ip_address="",
        mac_address="",
        wifi_signal="",
    )


async def test_title_updates_from_hub_info(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the config entry is renamed to the hub's own configured name."""
    mock_client.get_hub_info.return_value = _hub_info("Front Garage")
    await setup_integration(hass, mock_config_entry, [])

    assert mock_config_entry.title == "Front Garage"

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_title_unchanged_when_hub_info_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test setup doesn't fail or rename the entry if hub info can't be fetched."""
    mock_client.get_hub_info.side_effect = HubUnreachableError("boom")
    await setup_integration(hass, mock_config_entry, [])

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.title == "B&D Garage"

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_reloads_when_hub_reports_a_new_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a periodic check reloads the entry once a new device appears.

    Keeps the empty-platforms patch active across the reload too - unlike
    `setup_integration`, whose patch only covers the initial setup - so the
    reload doesn't try to actually load the real platform modules.
    """
    with patch("homeassistant.components.bnd_garage._PLATFORMS", []):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert len(mock_config_entry.runtime_data) == 1

        mock_client.get_device_ids.return_value = (TEST_DEVICE_ID, "device-b")
        async_fire_time_changed(hass, dt_util.utcnow() + _DEVICE_DISCOVERY_INTERVAL)
        await hass.async_block_till_done()

        assert mock_config_entry.data[CONF_DEVICE_IDS] == [TEST_DEVICE_ID, "device-b"]
        assert len(mock_config_entry.runtime_data) == 2

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_no_reload_when_device_list_unchanged(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the periodic check is a no-op when the hub reports nothing new."""
    with patch("homeassistant.components.bnd_garage._PLATFORMS", []):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        coordinators_before = mock_config_entry.runtime_data

        async_fire_time_changed(hass, dt_util.utcnow() + _DEVICE_DISCOVERY_INTERVAL)
        await hass.async_block_till_done()

        assert mock_config_entry.runtime_data is coordinators_before

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_periodic_check_ignores_hub_unreachable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a transient hub error during the periodic check doesn't crash."""
    with patch("homeassistant.components.bnd_garage._PLATFORMS", []):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        mock_client.get_device_ids.side_effect = HubUnreachableError("boom")

        async_fire_time_changed(hass, dt_util.utcnow() + _DEVICE_DISCOVERY_INTERVAL)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.LOADED

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
