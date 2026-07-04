"""Test move-to-position control."""

from unittest.mock import ANY, AsyncMock, patch

from bnd_garage_api import Client
from bnd_garage_api.models import DoorState, DoorStatus
import pytest

from homeassistant.components.bnd_garage.calibration import CalibrationCurve
from homeassistant.components.bnd_garage.set_position import async_set_position


@pytest.fixture(autouse=True)
def mock_sleep() -> AsyncMock:
    """Mock asyncio.sleep so tests run instantly and can assert durations."""
    with patch(
        "homeassistant.components.bnd_garage.set_position.asyncio.sleep", AsyncMock()
    ) as mock_sleep:
        yield mock_sleep


async def test_set_position_uses_curve_duration_when_available(
    mock_sleep: AsyncMock,
) -> None:
    """Test the estimated duration comes from the curve, not a flat rate."""
    client = AsyncMock(spec=Client)
    client.async_get_status.return_value = DoorStatus(
        state=DoorState.PARTIAL, position=80, rate=0
    )
    open_curve = CalibrationCurve(points=((0, 0), (10, 50), (20, 100)))

    status = await async_set_position(client, 0, 80, open_curve, None)

    client.async_open.assert_awaited_once()
    client.async_stop.assert_awaited_once()
    expected_duration = open_curve.time_at(80) - open_curve.time_at(0)
    mock_sleep.assert_awaited_once_with(expected_duration)
    assert status.position == 80


async def test_set_position_uses_flat_rate_when_uncalibrated(
    mock_sleep: AsyncMock,
) -> None:
    """Test a flat-rate estimate is used when no curve is available."""
    client = AsyncMock(spec=Client)
    client.async_get_status.side_effect = [
        DoorStatus(state=DoorState.MOVING, position=0, rate=10),
        DoorStatus(state=DoorState.PARTIAL, position=50, rate=0),
    ]

    status = await async_set_position(client, 0, 50, None, None)

    client.async_open.assert_awaited_once()
    client.async_stop.assert_awaited_once()
    assert mock_sleep.await_args_list == [ANY, ANY]
    assert status.position == 50


async def test_set_position_noop_when_already_at_target(
    mock_sleep: AsyncMock,
) -> None:
    """Test no command is sent when already at the requested position."""
    client = AsyncMock(spec=Client)
    client.async_get_status.return_value = DoorStatus(
        state=DoorState.PARTIAL, position=50, rate=0
    )

    status = await async_set_position(client, 50, 50, None, None)

    client.async_open.assert_not_awaited()
    client.async_close_door.assert_not_awaited()
    client.async_stop.assert_not_awaited()
    assert status.position == 50


async def test_set_position_no_correction_within_tolerance(
    mock_sleep: AsyncMock,
) -> None:
    """Test a result within TOLERANCE of the target isn't corrected further."""
    client = AsyncMock(spec=Client)
    client.async_get_status.return_value = DoorStatus(
        state=DoorState.PARTIAL, position=83, rate=0
    )
    open_curve = CalibrationCurve(points=((0, 0), (10, 100)))

    status = await async_set_position(client, 0, 80, open_curve, None)

    client.async_open.assert_awaited_once()
    assert status.position == 83


async def test_set_position_corrects_when_outside_tolerance(
    mock_sleep: AsyncMock,
) -> None:
    """Test a result outside TOLERANCE triggers exactly one correction move."""
    client = AsyncMock(spec=Client)
    client.async_get_status.side_effect = [
        DoorStatus(state=DoorState.MOVING, position=0, rate=10),
        DoorStatus(state=DoorState.PARTIAL, position=60, rate=0),  # 20 short of 80
        DoorStatus(state=DoorState.MOVING, position=60, rate=10),
        DoorStatus(
            state=DoorState.OPEN, position=80, rate=0
        ),  # correction lands on target
    ]

    status = await async_set_position(client, 0, 80, None, None)

    assert client.async_open.await_count == 2
    assert client.async_stop.await_count == 2
    assert status.position == 80


async def test_set_position_correction_reverses_direction_on_overshoot(
    mock_sleep: AsyncMock,
) -> None:
    """Test overshooting the target corrects by moving back the other way."""
    client = AsyncMock(spec=Client)
    client.async_get_status.side_effect = [
        DoorStatus(state=DoorState.MOVING, position=0, rate=10),
        DoorStatus(state=DoorState.OPEN, position=100, rate=0),  # overshot 80
        DoorStatus(state=DoorState.MOVING, position=100, rate=-10),
        DoorStatus(state=DoorState.PARTIAL, position=80, rate=0),
    ]

    status = await async_set_position(client, 0, 80, None, None)

    client.async_open.assert_awaited_once()
    client.async_close_door.assert_awaited_once()  # correction goes the other way
    assert status.position == 80
