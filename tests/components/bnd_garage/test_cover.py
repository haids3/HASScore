"""Test the B&D Garage cover entity."""

from unittest.mock import AsyncMock

from bnd_garage_client.errors import (
    AuthenticationError,
    HubCommandError,
    HubUnreachableError,
)
from bnd_garage_client.models import DoorState, HubStatus
import pytest

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import setup_integration

from tests.common import MockConfigEntry

ENTITY_ID = "cover.b_d_garage"


@pytest.fixture(autouse=True)
async def setup_cover(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Set up the integration with the cover platform loaded."""
    await setup_integration(hass, mock_config_entry, [Platform.COVER])


async def test_supported_features(hass: HomeAssistant) -> None:
    """Test the cover advertises open/close/stop."""
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["supported_features"] == (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )


@pytest.mark.parametrize(
    ("status", "expected_position", "expected_is_closed"),
    [
        pytest.param(
            HubStatus(state=DoorState.CLOSED, position=0, rate=0),
            0,
            True,
            id="closed",
        ),
        pytest.param(
            HubStatus(state=DoorState.OPEN, position=100, rate=0),
            100,
            False,
            id="open",
        ),
        pytest.param(
            HubStatus(state=DoorState.PARTIAL, position=42, rate=0),
            42,
            False,
            id="partial",
        ),
    ],
)
async def test_position_and_closed_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    status: HubStatus,
    expected_position: int,
    expected_is_closed: bool,
) -> None:
    """Test the reported position and closed state track the hub status."""
    mock_client.get_status.return_value = status
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["current_position"] == expected_position
    assert (state.state == "closed") is expected_is_closed


async def test_unknown_position_is_not_reported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test an unknown hub-reported position surfaces as no position, not -1."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.UNKNOWN, position=-1, rate=0
    )
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert "current_position" not in state.attributes


@pytest.mark.parametrize(
    ("rate", "expected_opening", "expected_closing"),
    [
        pytest.param(5, True, False, id="opening"),
        pytest.param(-5, False, True, id="closing"),
        pytest.param(0, False, False, id="stationary"),
    ],
)
async def test_moving_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    rate: int,
    expected_opening: bool,
    expected_closing: bool,
) -> None:
    """Test opening/closing are derived from the hub's reported rate."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING if rate else DoorState.CLOSED,
        position=50,
        rate=rate,
    )
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert (state.state == "opening") is expected_opening
    assert (state.state == "closing") is expected_closing


@pytest.mark.parametrize(
    ("service", "client_method"),
    [
        pytest.param("open_cover", "open_door", id="open"),
        pytest.param("close_cover", "close_door", id="close"),
        pytest.param("stop_cover", "stop_door", id="stop"),
    ],
)
async def test_commands(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    service: str,
    client_method: str,
) -> None:
    """Test open/close/stop services call through to the hub client."""
    await hass.services.async_call(
        "cover", service, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )

    getattr(mock_client, client_method).assert_awaited_once()


@pytest.mark.parametrize(
    "side_effect",
    [
        pytest.param(HubCommandError(16, "boom"), id="hub_command_error"),
        pytest.param(HubUnreachableError("boom"), id="cannot_connect"),
        pytest.param(AuthenticationError("boom"), id="invalid_auth"),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    side_effect: Exception,
) -> None:
    """Test hub command failures surface as HomeAssistantError."""
    mock_client.open_door.side_effect = side_effect

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "cover", "open_cover", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
        )
