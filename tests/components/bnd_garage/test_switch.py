"""Test the B&D Garage lockout and auxiliary switch entities."""

from unittest.mock import AsyncMock

from bnd_garage_client import ToggleState
from bnd_garage_client.errors import HubUnreachableError
from bnd_garage_client.models import DoorState, HubStatus
import pytest

from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import setup_integration
from .conftest import TEST_DEVICE_ID

from tests.common import MockConfigEntry

REMOTE_LOCKOUT_ENTITY_ID = "switch.b_d_garage_remote_control_lockout"
PHONE_LOCKOUT_ENTITY_ID = "switch.b_d_garage_phone_lockout"
AUXILIARY_ENTITY_ID = "switch.b_d_garage_auxiliary"


async def test_lockout_switches_not_created_when_hub_reports_none(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test lockout switches aren't created if the hub never reports the field."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    assert hass.states.get(REMOTE_LOCKOUT_ENTITY_ID) is None
    assert hass.states.get(PHONE_LOCKOUT_ENTITY_ID) is None
    assert hass.states.get(AUXILIARY_ENTITY_ID) is None


@pytest.mark.parametrize(
    ("locked", "expected_state"),
    [
        pytest.param(True, "on", id="locked"),
        pytest.param(False, "off", id="unlocked"),
    ],
)
async def test_remote_control_lockout_state_tracks_hub(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    locked: bool,
    expected_state: str,
) -> None:
    """Test the switch's on/off state tracks the hub's reported lockout toggle."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        remote_control_lockout=ToggleState(command=21 if locked else 20, is_on=locked),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    state = hass.states.get(REMOTE_LOCKOUT_ENTITY_ID)
    assert state is not None
    assert state.state == expected_state


async def test_remote_control_lockout_turn_on_calls_client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning on calls the client only if not already locked out."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        remote_control_lockout=ToggleState(command=20, is_on=False),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: REMOTE_LOCKOUT_ENTITY_ID}, blocking=True
    )

    mock_client.set_remote_control_lockout.assert_awaited_once_with(
        TEST_DEVICE_ID, True
    )


async def test_remote_control_lockout_turn_on_is_noop_when_already_locked(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning on does nothing if already locked out."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        remote_control_lockout=ToggleState(command=21, is_on=True),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: REMOTE_LOCKOUT_ENTITY_ID}, blocking=True
    )

    mock_client.set_remote_control_lockout.assert_not_awaited()


async def test_remote_control_lockout_turn_off_calls_client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning off calls the client only if currently locked out."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        remote_control_lockout=ToggleState(command=21, is_on=True),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: REMOTE_LOCKOUT_ENTITY_ID}, blocking=True
    )

    mock_client.set_remote_control_lockout.assert_awaited_once_with(
        TEST_DEVICE_ID, False
    )


@pytest.mark.parametrize(
    ("locked", "expected_state"),
    [
        pytest.param(True, "on", id="locked"),
        pytest.param(False, "off", id="unlocked"),
    ],
)
async def test_phone_lockout_state_tracks_hub(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    locked: bool,
    expected_state: str,
) -> None:
    """Test the switch's on/off state tracks the hub's reported lockout toggle."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        phone_lockout=ToggleState(command=257 if locked else 258, is_on=locked),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    state = hass.states.get(PHONE_LOCKOUT_ENTITY_ID)
    assert state is not None
    assert state.state == expected_state


async def test_phone_lockout_turn_on_calls_client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning on calls the client only if not already locked out."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        phone_lockout=ToggleState(command=258, is_on=False),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: PHONE_LOCKOUT_ENTITY_ID}, blocking=True
    )

    mock_client.set_phone_lockout.assert_awaited_once_with(TEST_DEVICE_ID, True)


async def test_phone_lockout_turn_off_calls_client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning off calls the client only if currently locked out."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        phone_lockout=ToggleState(command=257, is_on=True),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: PHONE_LOCKOUT_ENTITY_ID}, blocking=True
    )

    mock_client.set_phone_lockout.assert_awaited_once_with(TEST_DEVICE_ID, False)


async def test_phone_lockout_error_surfaces_as_home_assistant_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a hub command failure surfaces as HomeAssistantError."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        phone_lockout=ToggleState(command=258, is_on=False),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])
    mock_client.set_phone_lockout.side_effect = HubUnreachableError("boom")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: PHONE_LOCKOUT_ENTITY_ID},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("is_on", "expected_state"),
    [
        pytest.param(True, "on", id="on"),
        pytest.param(False, "off", id="off"),
    ],
)
async def test_auxiliary_state_tracks_hub(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    is_on: bool,
    expected_state: str,
) -> None:
    """Test the switch's on/off state tracks whichever cmd the hub currently lists."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        auxiliary=ToggleState(command=19 if is_on else 18, is_on=is_on),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    state = hass.states.get(AUXILIARY_ENTITY_ID)
    assert state is not None
    assert state.state == expected_state


async def test_auxiliary_turn_on_sends_cmd_only_when_currently_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning on sends the hub's cmd only if not already on."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        auxiliary=ToggleState(command=18, is_on=False),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: AUXILIARY_ENTITY_ID}, blocking=True
    )

    mock_client.send_command.assert_awaited_once_with(TEST_DEVICE_ID, 18)


async def test_auxiliary_turn_on_is_noop_when_already_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning on does nothing if already reported on."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        auxiliary=ToggleState(command=19, is_on=True),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: AUXILIARY_ENTITY_ID}, blocking=True
    )

    mock_client.send_command.assert_not_awaited()


async def test_auxiliary_turn_off_sends_cmd_only_when_currently_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test turning off sends the hub's cmd only if not already off."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        auxiliary=ToggleState(command=19, is_on=True),
    )
    await setup_integration(hass, mock_config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: AUXILIARY_ENTITY_ID}, blocking=True
    )

    mock_client.send_command.assert_awaited_once_with(TEST_DEVICE_ID, 19)
