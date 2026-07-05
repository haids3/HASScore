"""Test the B&D Garage preset button entities."""

from unittest.mock import AsyncMock

from bnd_garage_api import AuxAction
from bnd_garage_api.exceptions import CannotConnect
from bnd_garage_api.models import DoorState, DoorStatus
import pytest

from homeassistant.components.bnd_garage.coordinator import CONF_PRESET_POSITIONS
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import setup_integration

from tests.common import MockConfigEntry

PET_ENTITY_ID = "button.b_d_garage_pet"


async def test_no_buttons_created_when_hub_reports_no_presets(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test no button entities are created if the hub reports no presets."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])

    assert hass.states.async_entity_ids("button") == []


async def test_a_button_is_created_per_preset(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test one button entity is created for each preset the hub reports."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        presets=(
            AuxAction(cmd=5, title="Pet"),
            AuxAction(cmd=6, title="Parcel"),
            AuxAction(cmd=7, title="Ventilation"),
        ),
    )
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])

    assert set(hass.states.async_entity_ids("button")) == {
        "button.b_d_garage_pet",
        "button.b_d_garage_parcel",
        "button.b_d_garage_ventilation",
    }


async def test_button_press_activates_preset(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test pressing a preset button sends its cmd code to the hub."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        presets=(AuxAction(cmd=5, title="Pet"),),
    )
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: PET_ENTITY_ID}, blocking=True
    )

    mock_client.async_send_command.assert_awaited_once_with(5)


async def test_button_press_error_surfaces_as_home_assistant_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a hub command failure while pressing surfaces as HomeAssistantError."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        presets=(AuxAction(cmd=5, title="Pet"),),
    )
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])
    mock_client.async_send_command.side_effect = CannotConnect("boom")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: PET_ENTITY_ID}, blocking=True
        )


async def test_button_name_updates_when_hub_title_changes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the button's name is read live, reflecting a rename in the vendor app."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        presets=(AuxAction(cmd=5, title="Pet"),),
    )
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])
    coordinator = mock_config_entry.runtime_data

    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        presets=(AuxAction(cmd=5, title="Doggy Door"),),
    )
    await coordinator.async_refresh()

    state = hass.states.get(PET_ENTITY_ID)
    assert state is not None
    assert state.attributes["friendly_name"] == "B&D Garage Doggy Door"


async def test_button_becomes_unavailable_if_preset_removed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the button becomes unavailable if the hub stops reporting it."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        presets=(AuxAction(cmd=5, title="Pet"),),
    )
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])
    coordinator = mock_config_entry.runtime_data

    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED, position=0, rate=0, presets=()
    )
    await coordinator.async_refresh()

    state = hass.states.get(PET_ENTITY_ID)
    assert state is not None
    assert state.state == "unavailable"


async def test_last_position_recorded_after_preset_settles(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the position the door settles at after a preset press gets saved."""
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.CLOSED,
        position=0,
        rate=0,
        presets=(AuxAction(cmd=5, title="Pet"),),
    )
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])

    # The refresh triggered by the button press itself sees the door already
    # moving (matches every real hub response captured so far).
    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.MOVING,
        position=0,
        rate=7,
        presets=(AuxAction(cmd=5, title="Pet"),),
    )
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: PET_ENTITY_ID}, blocking=True
    )

    mock_client.async_get_status.return_value = DoorStatus(
        state=DoorState.PARTIAL,
        position=16,
        rate=0,
        presets=(AuxAction(cmd=5, title="Pet"),),
    )
    await mock_config_entry.runtime_data.async_refresh()

    state = hass.states.get(PET_ENTITY_ID)
    assert state is not None
    assert state.attributes["last_position"] == 16
    assert mock_config_entry.options[CONF_PRESET_POSITIONS] == {"5": 16}
