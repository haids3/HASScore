"""Test the B&D Garage activity sensor."""

from unittest.mock import AsyncMock

from bnd_garage_client import ActivityLogEntry
from bnd_garage_client.models import DoorState, HubStatus

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from . import setup_integration

from tests.common import MockConfigEntry

ENTITY_ID = "sensor.b_d_garage_last_activity"


async def test_sensor_not_created_when_hub_reports_no_activity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test no sensor is created if the hub never reports an activity log."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    await setup_integration(hass, mock_config_entry, [Platform.SENSOR])

    assert hass.states.get(ENTITY_ID) is None


async def test_sensor_state_and_attributes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the sensor's state and attributes reflect the hub's activity log."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        activity=ActivityLogEntry(
            text="Closed by HomeAssistant", log_id=123, logged_at=1783233784793, alert=0
        ),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SENSOR])

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "Closed by HomeAssistant"
    assert state.attributes["logged_at"] == 1783233784793
    assert state.attributes["alert"] == 0


async def test_sensor_updates_on_new_activity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the sensor's state changes when the hub reports a new log entry."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        activity=ActivityLogEntry(
            text="Closed by HomeAssistant", log_id=123, logged_at=1783233784793, alert=0
        ),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SENSOR])

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        activity=ActivityLogEntry(
            text="Light off by HomeAssistant",
            log_id=124,
            logged_at=1783233800000,
            alert=0,
        ),
    )
    await mock_config_entry.runtime_data[0].async_refresh()

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "Light off by HomeAssistant"
