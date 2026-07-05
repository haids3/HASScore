"""Test the B&D Garage hub light entity."""

from unittest.mock import AsyncMock

from bnd_garage_api import ToggleAction
from bnd_garage_api.exceptions import CannotConnect
from bnd_garage_api.models import DoorState, DoorStatus
import pytest

from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import setup_integration

from tests.common import MockConfigEntry

ENTITY_ID = "light.b_d_garage_light"


async def test_light_not_created_when_hub_reports_none(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test no light entity is created if the hub never reports a light action."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    await setup_integration(hass, mock_config_entry, [Platform.LIGHT])

    assert hass.states.get(ENTITY_ID) is None


@pytest.mark.parametrize(
    ("is_on", "expected_state"),
    [
        pytest.param(True, "on", id="on"),
        pytest.param(False, "off", id="off"),
    ],
)
async def test_light_state_tracks_hub(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    is_on: bool,
    expected_state: str,
) -> None:
    """Test the light's on/off state tracks whichever cmd the hub currently lists."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        light=ToggleAction(cmd=17 if is_on else 16, is_on=is_on),
    )
    await setup_integration(hass, mock_config_entry, [Platform.LIGHT])

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == expected_state


async def test_turn_on_sends_cmd_only_when_currently_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning on sends the hub's cmd only if the light isn't already on."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        light=ToggleAction(cmd=16, is_on=False),
    )
    await setup_integration(hass, mock_config_entry, [Platform.LIGHT])

    await hass.services.async_call(
        "light", "turn_on", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )

    mock_client.async_send_command.assert_awaited_once_with(16)


async def test_turn_on_is_noop_when_already_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning on does nothing if the light is already reported on."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        light=ToggleAction(cmd=17, is_on=True),
    )
    await setup_integration(hass, mock_config_entry, [Platform.LIGHT])

    await hass.services.async_call(
        "light", "turn_on", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )

    mock_client.async_send_command.assert_not_awaited()


async def test_turn_off_sends_cmd_only_when_currently_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning off sends the hub's cmd only if the light isn't already off."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        light=ToggleAction(cmd=17, is_on=True),
    )
    await setup_integration(hass, mock_config_entry, [Platform.LIGHT])

    await hass.services.async_call(
        "light", "turn_off", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )

    mock_client.async_send_command.assert_awaited_once_with(17)


async def test_turn_on_error_surfaces_as_home_assistant_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a hub command failure surfaces as HomeAssistantError."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        light=ToggleAction(cmd=16, is_on=False),
    )
    await setup_integration(hass, mock_config_entry, [Platform.LIGHT])
    mock_client.async_send_command.side_effect = CannotConnect("boom")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "light", "turn_on", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
        )
