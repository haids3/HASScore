"""Test travel-time calibration."""

from itertools import count
from unittest.mock import AsyncMock, patch

from bnd_garage_api.models import DoorState, DoorStatus
import pytest

from homeassistant.components.bnd_garage.calibration import (
    CalibrationCurve,
    async_calibrate,
)


class FakeClient:
    """Fake hub client simulating open/close/stop for calibration tests.

    Each stop advances position by a fixed step in the current direction;
    letting movement run without an explicit stop reaches the far extreme,
    simulating the "final leg runs to completion" behavior.
    """

    def __init__(self, start_position: int) -> None:
        """Initialize the fake client at the given starting position."""
        self.position = start_position
        self.moving = False
        self.opening = True
        self.direction_log: list[str] = []
        self.stop_calls = 0
        self._polls_since_move_started = 0

    async def async_open(self) -> None:
        """Simulate sending the open command."""
        self.direction_log.append("open")
        self._start_moving(opening=True)

    async def async_close_door(self) -> None:
        """Simulate sending the close command."""
        self.direction_log.append("close")
        self._start_moving(opening=False)

    def _start_moving(self, *, opening: bool) -> None:
        self.moving = True
        self.opening = opening
        self._polls_since_move_started = 0

    async def async_stop(self) -> None:
        """Simulate sending the stop command, advancing position by one step."""
        self.stop_calls += 1
        self.moving = False
        delta = 10 if self.opening else -10
        self.position = max(0, min(100, self.position + delta))

    async def async_get_status(self) -> DoorStatus:
        """Simulate a status poll, reaching the far extreme after one more poll."""
        if self.moving:
            self._polls_since_move_started += 1
            if self._polls_since_move_started > 1:
                self.moving = False
                self.position = 100 if self.opening else 0
            else:
                rate = 10.0 if self.opening else -10.0
                return DoorStatus(
                    state=DoorState.MOVING, position=self.position, rate=rate
                )

        if self.position == 0:
            state = DoorState.CLOSED
        elif self.position == 100:
            state = DoorState.OPEN
        else:
            state = DoorState.PARTIAL
        return DoorStatus(state=state, position=self.position, rate=0)


@pytest.fixture(autouse=True)
def _no_real_sleep() -> None:
    with patch(
        "homeassistant.components.bnd_garage.calibration.asyncio.sleep", AsyncMock()
    ):
        yield


@pytest.fixture(autouse=True)
def _fake_clock() -> None:
    with patch(
        "homeassistant.components.bnd_garage.calibration.time.monotonic",
        side_effect=count(0.0, 1.0),
    ):
        yield


def _direction_passes(log: list[str]) -> list[str]:
    """Collapse a direction log into contiguous passes, e.g. ["open", "open", "close"] -> ["open", "close"]."""
    passes: list[str] = []
    for direction in log:
        if not passes or passes[-1] != direction:
            passes.append(direction)
    return passes


async def test_calibrate_from_closed_runs_open_pass_then_close_pass() -> None:
    """Test calibration from closed does exactly one open pass, one close pass."""
    client = FakeClient(start_position=0)

    open_curve, close_curve = await async_calibrate(client)

    assert _direction_passes(client.direction_log) == ["open", "close"]
    assert open_curve.points[0] == (0.0, 0)
    assert open_curve.points[-1][1] == 100
    assert close_curve.points[0][1] == 100
    assert close_curve.points[-1][1] == 0


async def test_calibrate_from_open_runs_close_pass_then_open_pass() -> None:
    """Test calibration from open does exactly one close pass, one open pass."""
    client = FakeClient(start_position=100)

    open_curve, close_curve = await async_calibrate(client)

    assert _direction_passes(client.direction_log) == ["close", "open"]
    assert close_curve.points[0] == (0.0, 100)
    assert close_curve.points[-1][1] == 0
    assert open_curve.points[0][1] == 0
    assert open_curve.points[-1][1] == 100


async def test_calibrate_records_monotonic_positions() -> None:
    """Test each curve's recorded positions move consistently in one direction."""
    client = FakeClient(start_position=0)

    open_curve, close_curve = await async_calibrate(client)

    open_positions = [p for _, p in open_curve.points]
    close_positions = [p for _, p in close_curve.points]
    assert open_positions == sorted(open_positions)
    assert close_positions == sorted(close_positions, reverse=True)


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        pytest.param(0, 0, id="at-start"),
        pytest.param(2.5, 25, id="midpoint"),
        pytest.param(10, 100, id="at-end"),
        pytest.param(-5, 0, id="before-start-clamped"),
        pytest.param(20, 100, id="after-end-clamped"),
    ],
)
def test_curve_position_at_interpolates(elapsed: float, expected: int) -> None:
    """Test position_at interpolates between measured points."""
    curve = CalibrationCurve(points=((0, 0), (5, 50), (10, 100)))
    assert curve.position_at(elapsed) == expected


def test_curve_position_at_reflects_deceleration_near_limits() -> None:
    """Test a non-linear curve is honored, not flattened to a straight line."""
    # Real doors decelerate near the limits: big jump early, small near the end.
    curve = CalibrationCurve(points=((0, 0), (2, 70), (10, 100)))
    assert curve.position_at(1) == 35  # fast segment
    assert curve.position_at(6) == 85  # slow segment


def test_curve_json_round_trip() -> None:
    """Test the curve survives a to_json/from_json round trip."""
    curve = CalibrationCurve(points=((0.0, 0), (5.0, 50), (10.0, 100)))
    assert CalibrationCurve.from_json(curve.to_json()) == curve


def test_curve_from_json_none_when_never_calibrated() -> None:
    """Test from_json returns None for missing/empty data."""
    assert CalibrationCurve.from_json(None) is None
    assert CalibrationCurve.from_json([]) is None
