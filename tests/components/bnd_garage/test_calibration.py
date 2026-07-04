"""Test travel-time calibration."""

from itertools import count
from unittest.mock import AsyncMock, patch

from bnd_garage_api.models import DoorState, DoorStatus
import pytest

from homeassistant.components.bnd_garage.calibration import (
    EDGE_DISTANCE_FRACTION,
    EDGE_SPEED_FACTOR,
    CalibrationCurve,
    async_calibrate,
    build_curve,
)


class FakeClient:
    """Fake hub client simulating one continuous open/close/stop cycle."""

    def __init__(self, start_position: int) -> None:
        """Initialize the fake client at the given starting position."""
        self.position = start_position
        self.moving = False
        self.opening = True
        self.direction_log: list[str] = []

    async def async_open(self) -> None:
        """Simulate sending the open command."""
        self.direction_log.append("open")
        self.moving = True
        self.opening = True

    async def async_close_door(self) -> None:
        """Simulate sending the close command."""
        self.direction_log.append("close")
        self.moving = True
        self.opening = False

    async def async_stop(self) -> None:
        """Simulate sending the stop command (unused - moves run to completion)."""

    async def async_get_status(self) -> DoorStatus:
        """Simulate a status poll, reaching the far extreme on the first poll."""
        if self.moving:
            self.moving = False
            self.position = 100 if self.opening else 0
            return DoorStatus(
                state=DoorState.OPEN if self.opening else DoorState.CLOSED,
                position=self.position,
                rate=0,
            )

        if self.position == 0:
            state = DoorState.CLOSED
        elif self.position == 100:
            state = DoorState.OPEN
        else:
            state = DoorState.PARTIAL
        return DoorStatus(state=state, position=self.position, rate=0)


@pytest.fixture(autouse=True)
def mock_sleep() -> AsyncMock:
    """Mock asyncio.sleep so tests run instantly."""
    with patch(
        "homeassistant.components.bnd_garage.hub_control.asyncio.sleep", AsyncMock()
    ) as mock_sleep:
        yield mock_sleep


@pytest.fixture(autouse=True)
def fake_clock() -> None:
    """Advance a fake monotonic clock by 1s per call, for deterministic timing."""
    with patch(
        "homeassistant.components.bnd_garage.calibration.time.monotonic",
        side_effect=count(0.0, 1.0),
    ):
        yield


def _direction_passes(log: list[str]) -> list[str]:
    """Collapse a direction log into contiguous passes."""
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


async def test_calibrate_from_partial_repositions_to_nearer_extreme_first() -> None:
    """Test a partial start repositions to a true extreme before either pass.

    Otherwise the first pass would be anchored at the partial position
    instead of 0/100, producing a curve the coordinator can never match
    against a real future full-range movement - silently wasted data.
    """
    client = FakeClient(start_position=40)  # closer to closed

    open_curve, close_curve = await async_calibrate(client)

    assert _direction_passes(client.direction_log) == ["close", "open", "close"]
    assert open_curve.points[0] == (0.0, 0)
    assert open_curve.points[-1][1] == 100
    assert close_curve.points[0] == (0.0, 100)
    assert close_curve.points[-1][1] == 0


def test_build_curve_has_slow_edges_and_fast_middle() -> None:
    """Test the standard shape: slow first/last EDGE_DISTANCE_FRACTION, fast middle.

    This is a deliberate assumption, not a per-installation measurement -
    confirmed against real hardware that repeatedly stopping to sample
    intermediate positions re-triggers the motor's soft-start ramp-up on
    every restart, contaminating a directly-measured shape far worse than
    assuming a standard one.
    """
    curve = build_curve(0, 100, total_time=16.0)

    edge_time = 16.0 * EDGE_DISTANCE_FRACTION / EDGE_SPEED_FACTOR
    assert curve.points == (
        (0.0, 0),
        (pytest.approx(edge_time), 10),
        (pytest.approx(16.0 - edge_time), 90),
        (16.0, 100),
    )
    # Middle segment covers 80% of distance in 60% of time - faster than the
    # edges, which cover 10% of distance in 20% of time each.
    middle_rate = 80 / (16.0 - 2 * edge_time)
    edge_rate = 10 / edge_time
    assert middle_rate > edge_rate


def test_build_curve_works_for_closing_direction() -> None:
    """Test the standard shape applies symmetrically to a closing movement."""
    curve = build_curve(100, 0, total_time=20.0)

    assert curve.points[0] == (0.0, 100)
    assert curve.points[-1] == (20.0, 0)
    assert curve.points[1][1] == 90  # first edge: 10% closed after 20% of time
    assert curve.points[2][1] == 10  # last edge starts: 90% closed


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


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        pytest.param(0, 0, id="at-start"),
        pytest.param(25, 2.5, id="midpoint"),
        pytest.param(100, 10, id="at-end"),
        pytest.param(-10, 0, id="before-start-clamped"),
        pytest.param(110, 10, id="after-end-clamped"),
    ],
)
def test_curve_time_at_interpolates_opening_curve(
    position: int, expected: float
) -> None:
    """Test time_at inverts position_at for an increasing (opening) curve."""
    curve = CalibrationCurve(points=((0, 0), (5, 50), (10, 100)))
    assert curve.time_at(position) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        pytest.param(100, 0, id="at-start"),
        pytest.param(50, 5, id="midpoint"),
        pytest.param(0, 10, id="at-end"),
        pytest.param(110, 0, id="above-start-clamped"),
        pytest.param(-10, 10, id="below-end-clamped"),
    ],
)
def test_curve_time_at_interpolates_closing_curve(
    position: int, expected: float
) -> None:
    """Test time_at also works for a decreasing (closing) curve."""
    curve = CalibrationCurve(points=((0, 100), (5, 50), (10, 0)))
    assert curve.time_at(position) == pytest.approx(expected)


def test_curve_json_round_trip() -> None:
    """Test the curve survives a to_json/from_json round trip."""
    curve = CalibrationCurve(points=((0.0, 0), (5.0, 50), (10.0, 100)))
    assert CalibrationCurve.from_json(curve.to_json()) == curve


def test_curve_from_json_none_when_never_calibrated() -> None:
    """Test from_json returns None for missing/empty data."""
    assert CalibrationCurve.from_json(None) is None
    assert CalibrationCurve.from_json([]) is None
