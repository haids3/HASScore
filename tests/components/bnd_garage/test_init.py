"""Test the B&D Garage integration setup."""

from unittest.mock import AsyncMock

from bnd_garage_client.errors import AuthenticationError, HubUnreachableError
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import setup_integration
from .conftest import TEST_HUB_ID

from tests.common import MockConfigEntry


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
    assert entries[0].unique_id == TEST_HUB_ID

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
