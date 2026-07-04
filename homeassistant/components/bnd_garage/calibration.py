"""Travel-time calibration for the B&D Garage integration.

Real garage doors decelerate near their open/closed limits, so a single
average rate (what DataUpdateCoordinator falls back to when uncalibrated)
isn't accurate there. This times one continuous, uninterrupted full-range
movement per direction, then builds a standard-shaped curve around that
real measured total time: the first and last EDGE_DISTANCE_FRACTION of
travel at EDGE_SPEED_FACTOR times the average rate (motor soft-start
ramp-up, and mechanical deceleration approaching the limit), the middle
faster to match.

This deliberately does NOT measure the curve's shape by stopping and
checking position at intermediate ~10% marks. Confirmed against real
hardware: doing that repeatedly stops and restarts the door, and each
restart re-triggers the motor's own soft-start ramp-up - so a curve built
that way accumulates *nine* ramp-ups instead of the *one* a real continuous
move actually has, measuring roughly 60% slower than reality. There's no
way to sample true intermediate position without stopping (the hub only
reports position at rest), so a real per-installation shape isn't
obtainable this way at all - the standard shape assumption is a deliberate
trade of shape precision for not contaminating the one number (total time)
that matters most.

Drives the door through exactly one open pass and one close pass, in
whichever order gets there first - unless the door is already sitting at a
partial position (not fully open or closed), in which case it repositions
to the nearer extreme first. A pass that doesn't start from a true extreme
would produce a curve the coordinator can never actually use later, so that
repositioning step isn't optional the way an unconditional "always start
by closing" step would be - it's only added when genuinely needed, not on
every run.
"""

from dataclasses import dataclass
from itertools import pairwise
import logging
import time
from typing import Self

from bnd_garage_api import Client

from .hub_control import async_send_direction, async_wait_until_stopped

_LOGGER = logging.getLogger(__name__)

EDGE_DISTANCE_FRACTION = 0.10
EDGE_SPEED_FACTOR = 0.5


@dataclass(frozen=True)
class CalibrationCurve:
    """Measured (elapsed_seconds, position) points for one travel direction."""

    points: tuple[tuple[float, int], ...]

    def position_at(self, elapsed: float) -> int:
        """Interpolate position at the given elapsed time from measured points."""
        points = self.points
        if elapsed <= points[0][0]:
            return points[0][1]
        for (t0, p0), (t1, p1) in pairwise(points):
            if elapsed <= t1:
                if t1 == t0:
                    return p1
                fraction = (elapsed - t0) / (t1 - t0)
                return round(p0 + (p1 - p0) * fraction)
        return points[-1][1]

    def time_at(self, position: int) -> float:
        """Interpolate elapsed time for the given position (inverse of position_at).

        Works for both open curves (position increasing) and close curves
        (position decreasing) - direction is inferred from the first/last
        point rather than assumed.
        """
        points = self.points
        first_t, first_p = points[0]
        last_t, last_p = points[-1]
        increasing = last_p >= first_p

        if (increasing and position <= first_p) or (
            not increasing and position >= first_p
        ):
            return first_t
        if (increasing and position >= last_p) or (
            not increasing and position <= last_p
        ):
            return last_t

        for (t0, p0), (t1, p1) in pairwise(points):
            if (increasing and p0 <= position <= p1) or (
                not increasing and p1 <= position <= p0
            ):
                if p1 == p0:
                    return t1
                fraction = (position - p0) / (p1 - p0)
                return t0 + (t1 - t0) * fraction
        return last_t

    def to_json(self) -> list[list[float]]:
        """Serialize for storage in config entry options."""
        return [[t, p] for t, p in self.points]

    @classmethod
    def from_json(cls, data: list[list[float]] | None) -> Self | None:
        """Deserialize from config entry options; None if never calibrated."""
        if not data:
            return None
        return cls(points=tuple((t, int(p)) for t, p in data))


async def async_calibrate(client: Client) -> tuple[CalibrationCurve, CalibrationCurve]:
    """Measure real open and close travel times against the hub.

    Runs exactly one open pass and one close pass, in whichever order gets
    there first. If the door isn't already sitting at a known extreme (fully
    open or fully closed), it's repositioned to the nearer one first - a
    pass that doesn't start from a true extreme would produce a curve the
    coordinator can never actually use later, so this step is only added
    when genuinely needed, not on every run.
    """
    _LOGGER.debug("Starting travel calibration")
    status = await async_wait_until_stopped(client)

    if status.position not in (0, 100):
        # Continue toward the nearer extreme, not the farther one.
        await async_send_direction(client, opening=status.position >= 50)
        status = await async_wait_until_stopped(client)

    if status.position == 0:
        open_curve = await _measure(client, opening=True, start_position=0)
        close_curve = await _measure(client, opening=False, start_position=100)
    else:
        close_curve = await _measure(client, opening=False, start_position=100)
        open_curve = await _measure(client, opening=True, start_position=0)

    _LOGGER.debug("Calibration complete: open=%s close=%s", open_curve, close_curve)
    return open_curve, close_curve


async def _measure(
    client: Client, *, opening: bool, start_position: int
) -> CalibrationCurve:
    """Time one continuous, uninterrupted move, then build a standard curve."""
    await async_send_direction(client, opening=opening)
    # Anchored after send_direction returns (not before), since that's what
    # set_position.py also does before its own timed sleep - both need to
    # measure from the same reference point to be comparable.
    start = time.monotonic()
    status = await async_wait_until_stopped(client)
    total_time = time.monotonic() - start
    return build_curve(start_position, status.position, total_time)


def build_curve(
    start_position: int, end_position: int, total_time: float
) -> CalibrationCurve:
    """Build a standard-shaped curve from one measured continuous movement.

    Shared by the explicit calibration routine above and the coordinator's
    passive auto-calibration, which builds the same shape from the timing of
    an ordinary full-range open/close during regular use.
    """
    distance = end_position - start_position
    edge_distance = distance * EDGE_DISTANCE_FRACTION
    edge_time = total_time * EDGE_DISTANCE_FRACTION / EDGE_SPEED_FACTOR

    points = (
        (0.0, start_position),
        (edge_time, round(start_position + edge_distance)),
        (total_time - edge_time, round(end_position - edge_distance)),
        (total_time, end_position),
    )
    return CalibrationCurve(points=points)
