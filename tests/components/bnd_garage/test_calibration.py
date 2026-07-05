"""Test travel-time calibration."""

import pytest

from homeassistant.components.bnd_garage.calibration import (
    EDGE_DISTANCE_FRACTION,
    EDGE_SPEED_FACTOR,
    CalibrationCurve,
    build_curve,
)


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


def test_curve_json_round_trip() -> None:
    """Test the curve survives a to_json/from_json round trip."""
    curve = CalibrationCurve(points=((0.0, 0), (5.0, 50), (10.0, 100)))
    assert CalibrationCurve.from_json(curve.to_json()) == curve


def test_curve_from_json_none_when_never_calibrated() -> None:
    """Test from_json returns None for missing/empty data."""
    assert CalibrationCurve.from_json(None) is None
    assert CalibrationCurve.from_json([]) is None
