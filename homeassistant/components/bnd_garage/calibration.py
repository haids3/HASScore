"""Travel-time calibration for the B&D Garage integration.

Real garage doors decelerate near their open/closed limits, so a single
average rate (what DataUpdateCoordinator falls back to when uncalibrated)
isn't accurate there. This drives the door in ~10% steps, stopping at each
one and reading the hub's actual at-rest position, to build a real
elapsed-time-to-position curve per direction instead of assuming a constant
rate throughout.

Drives the door through exactly one open pass and one close pass, in
whichever order gets there first - unless the door is already sitting at a
partial position (not fully open or closed), in which case it repositions
to the nearer extreme first. A pass that doesn't start from a true extreme
would produce a curve the coordinator can never actually use later, so that
repositioning step isn't optional the way an unconditional "always start
by closing" step would be - it's only added when genuinely needed, not on
every run.
"""

import asyncio
from dataclasses import dataclass
from itertools import pairwise
import logging
import time
from typing import Self

from bnd_garage_api import Client, DoorState, DoorStatus

_LOGGER = logging.getLogger(__name__)

STEP_COUNT = 9
STEP_STARTUP_DELAY = 0.5
SETTLE_TIMEOUT = 15.0
POLL_INTERVAL = 0.5
FALLBACK_RATE = 7.0


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
    """Measure real open and close travel curves against the hub.

    Runs exactly one open pass and one close pass, in whichever order gets
    there first. If the door isn't already sitting at a known extreme (fully
    open or fully closed), it's repositioned to the nearer one first - a
    pass that doesn't start from a true extreme would produce a curve the
    coordinator can never actually use later, so this step is only added
    when genuinely needed, not on every run.
    """
    _LOGGER.debug("Starting travel calibration")
    status = await _wait_until_stopped(client)

    if status.position not in (0, 100):
        # Continue toward the nearer extreme, not the farther one.
        await _send_direction(client, opening=status.position >= 50)
        status = await _wait_until_stopped(client)

    if status.position == 0:
        open_curve = await _sweep(client, opening=True, start_position=0)
        close_curve = await _sweep(client, opening=False, start_position=100)
    else:
        close_curve = await _sweep(client, opening=False, start_position=100)
        open_curve = await _sweep(client, opening=True, start_position=0)

    _LOGGER.debug("Calibration complete: open=%s close=%s", open_curve, close_curve)
    return open_curve, close_curve


async def _sweep(
    client: Client, *, opening: bool, start_position: int
) -> CalibrationCurve:
    """Drive one direction in ~10% steps, recording actual rest positions."""
    points: list[tuple[float, int]] = [(0.0, start_position)]
    start = time.monotonic()
    position = start_position

    for _ in range(STEP_COUNT):
        if (opening and position >= 90) or (not opening and position <= 10):
            break

        await _send_direction(client, opening=opening)
        # Sample the hub's live rate shortly after it actually starts moving,
        # rather than reusing a stale rate from the last at-rest reading
        # (which is always 0), so the ~10% step timing is accurate.
        await asyncio.sleep(STEP_STARTUP_DELAY)
        moving_status = await client.async_get_status()
        rate = abs(moving_status.rate) or FALLBACK_RATE
        remaining = max(0.0, 10 / rate - STEP_STARTUP_DELAY)
        await asyncio.sleep(remaining)
        await client.async_stop()

        status = await _wait_until_stopped(client)
        position = status.position
        points.append((time.monotonic() - start, position))

    # Let the final leg run to completion naturally rather than guessing the
    # last stop - doors decelerate hardest right at the limits.
    await _send_direction(client, opening=opening)
    status = await _wait_until_stopped(client)
    points.append((time.monotonic() - start, status.position))

    return CalibrationCurve(points=tuple(points))


async def _send_direction(client: Client, *, opening: bool) -> None:
    """Send the open or close command for this sweep's direction."""
    if opening:
        await client.async_open()
    else:
        await client.async_close_door()


async def _wait_until_stopped(client: Client) -> DoorStatus:
    """Poll until the hub reports the door is no longer moving."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    status = await client.async_get_status()
    while status.state == DoorState.MOVING and time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        status = await client.async_get_status()
    return status
