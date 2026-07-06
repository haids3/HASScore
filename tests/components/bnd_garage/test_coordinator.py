"""Test the B&D Garage coordinator's adaptive poll interval."""

from unittest.mock import AsyncMock, patch

from bnd_garage_client.models import DoorState, HubStatus
import pytest

from homeassistant.components.bnd_garage.calibration import CalibrationCurve
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
    mock_client.get_status.return_value = HubStatus(
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
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=50, rate=5
    )
    await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data
    assert coordinator.update_interval == MOVING_UPDATE_INTERVAL

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.OPEN, position=100, rate=0
    )
    await coordinator.async_refresh()

    assert coordinator.update_interval == UPDATE_INTERVAL

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_moving_position_is_estimated_from_elapsed_time(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test position is extrapolated locally from elapsed time and rate."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=100.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=100.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 1  # clamped, elapsed == 0

    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=103.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 30  # 0 + 10%/s * 3s

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_moving_position_picks_up_rate_drift_mid_travel(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a same-direction rate change is picked up within one poll."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=300.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=300.0,
    ):
        await coordinator.async_refresh()

    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=302.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 20  # 0 + 10%/s * 2s

    # Same direction, but the hub now reports a slower rate.
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=5
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=304.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 40  # 20 + 10%/s * 2s (still-old rate)

    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=306.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 50  # 40 + 5%/s * 2s (new rate applied)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_moving_position_reanchors_on_direction_reversal(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a mid-travel direction reversal re-anchors from the current estimate."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=200.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=200.0,
    ):
        await coordinator.async_refresh()  # anchors here: elapsed 0, position 1

    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=203.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 30  # 0 + 10%/s * 3s

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=-10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=204.0,
    ):
        await coordinator.async_refresh()
    # Re-anchors from the 40 it would have reached by t=204 on the old
    # trajectory, not from the pre-movement position (0).
    assert coordinator.data.position == 40

    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=205.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 30  # 40 - 10%/s * 1s on the new rate

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_moving_position_uses_calibrated_curve(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a calibrated curve is used instead of the flat-rate estimate."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=400.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data
    coordinator.open_curve = CalibrationCurve(points=((0, 0), (5, 40), (10, 100)))

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=400.0,
    ):
        await coordinator.async_refresh()  # segment starts here, at the extreme

    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=405.0,
    ):
        await coordinator.async_refresh()
    # From the curve (5s -> 40), not the flat-rate estimate (0 + 10%/s * 5s = 50).
    assert coordinator.data.position == 40

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_moving_position_ignores_curve_when_not_starting_at_reference(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a movement starting mid-travel falls back to the flat-rate estimate."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.PARTIAL, position=30, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=500.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data
    coordinator.open_curve = CalibrationCurve(points=((0, 0), (5, 40), (10, 100)))

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=30, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=500.0,
    ):
        await coordinator.async_refresh()

    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=503.0,
    ):
        await coordinator.async_refresh()
    assert coordinator.data.position == 60  # 30 + 10%/s * 3s, curve not applicable

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_auto_calibrates_from_full_open_movement(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a normal full open passively builds the open curve."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=1000.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data
    assert coordinator.open_curve is None

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=1000.0,
    ):
        await coordinator.async_refresh()

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.OPEN, position=100, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=1016.0,
    ):
        await coordinator.async_refresh()

    assert coordinator.open_curve is not None
    assert coordinator.open_curve.points[0] == (0.0, 0)
    assert coordinator.open_curve.points[-1] == (16.0, 100)
    assert mock_config_entry.options["open_curve"] == coordinator.open_curve.to_json()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_auto_calibrates_from_full_close_movement(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a normal full close passively builds the close curve."""
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.OPEN, position=100, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=2000.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=100, rate=-10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=2000.0,
    ):
        await coordinator.async_refresh()

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=2020.0,
    ):
        await coordinator.async_refresh()

    assert coordinator.close_curve is not None
    assert coordinator.close_curve.points[0] == (0.0, 100)
    assert coordinator.close_curve.points[-1] == (20.0, 0)
    assert mock_config_entry.options["close_curve"] == coordinator.close_curve.to_json()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_auto_calibrate_skips_movement_not_starting_at_extreme(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test resuming from a partial position doesn't produce a curve.

    That segment can't represent the full 0-100 range, so a curve built
    from it would never match a real future full-range movement anyway.
    """
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.PARTIAL, position=30, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=3000.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=30, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=3000.0,
    ):
        await coordinator.async_refresh()

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.OPEN, position=100, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=3010.0,
    ):
        await coordinator.async_refresh()

    assert coordinator.open_curve is None
    assert "open_curve" not in mock_config_entry.options

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_auto_calibrate_skips_movement_stopped_short_of_extreme(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test a movement that stops short of the far extreme isn't calibrated.

    E.g. an obstruction safety-stop partway through - that's not a
    representative full-range measurement.
    """
    mock_client.get_status.return_value = HubStatus(
        state=DoorState.CLOSED, position=0, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=4000.0,
    ):
        await setup_integration(hass, mock_config_entry, [])
    coordinator = mock_config_entry.runtime_data

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.MOVING, position=0, rate=10
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=4000.0,
    ):
        await coordinator.async_refresh()

    mock_client.get_status.return_value = HubStatus(
        state=DoorState.PARTIAL, position=60, rate=0
    )
    with patch(
        "homeassistant.components.bnd_garage.coordinator.time.monotonic",
        return_value=4008.0,
    ):
        await coordinator.async_refresh()

    assert coordinator.open_curve is None
    assert "open_curve" not in mock_config_entry.options

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
