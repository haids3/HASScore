"""Test the B&D Garage calibration button."""

from unittest.mock import AsyncMock

from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant

from . import setup_integration

from tests.common import MockConfigEntry

ENTITY_ID = "button.b_d_garage_calibrate_travel_time"


async def test_button_triggers_calibration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test pressing the button calls the coordinator's calibration routine."""
    await setup_integration(hass, mock_config_entry, [Platform.BUTTON])
    coordinator = mock_config_entry.runtime_data
    coordinator.async_calibrate = AsyncMock()

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )

    coordinator.async_calibrate.assert_awaited_once()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
