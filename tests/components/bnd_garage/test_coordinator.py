"""Test the B&D Garage coordinator's adaptive poll interval."""

from unittest.mock import AsyncMock

from bnd_garage_api.models import DoorState, DoorStatus
import pytest

from homeassistant.components.bnd_garage.coordinator import (
    MOVING_UPDATE_INTERVAL,
    UPDATE_INTERVAL,
)
from homeassistant.core import HomeAssistant

from . import setup_integration

from tests.common import MockConfigEntry


@pytest.mark.parametrize(
    ("state", "expected_interval"),
    [
        pytest.param(DoorState.MOVING, MOVING_UPDATE_INTERVAL, id="moving"),
        pytest.param(DoorState.OPEN, UPDATE_INTERVAL, id="open"),
        pytest.param(DoorState.CLOSED, UPDATE_INTERVAL, id="closed"),
        pytest.param(DoorState.PARTIAL, UPDATE_INTERVAL, id="partial"),
    ],
)
async def test_poll_interval_tracks_door_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    state: DoorState,
    expected_interval: object,
) -> None:
    """Test the coordinator speeds up while the door is moving and slows back down."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=state, position=50, rate=5 if state == DoorState.MOVING else 0
    )
    await setup_integration(hass, mock_config_entry, [])

    assert mock_config_entry.runtime_data.update_interval == expected_interval

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_poll_interval_reverts_after_movement_stops(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the interval returns to normal once the door stops moving."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.MOVING, position=50, rate=5
    )
    await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data
    assert coordinator.update_interval == MOVING_UPDATE_INTERVAL

    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.OPEN, position=100, rate=0
    )
    await coordinator.async_refresh()

    assert coordinator.update_interval == UPDATE_INTERVAL

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
