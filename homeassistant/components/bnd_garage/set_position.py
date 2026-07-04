"""Move-to-position control for the B&D Garage integration.

The hub only supports open/close/stop, not "go to position N" - this drives
the door for an estimated duration (from the calibrated travel curve if
available, otherwise a flat-rate estimate from the hub's live-reported
rate), then checks the hub's actual at-rest position. If that's outside
TOLERANCE of the target, it does one corrective move for the remaining
distance using the same estimation method - not further iteration, since
each additional correction buys diminishing accuracy for the cost of
another stop/start cycle on the door.
"""

import asyncio
import logging

from bnd_garage_api import Client, DoorStatus

from .calibration import CalibrationCurve
from .hub_control import FALLBACK_RATE, async_send_direction, async_wait_until_stopped

_LOGGER = logging.getLogger(__name__)

TOLERANCE = 5
STEP_STARTUP_DELAY = 0.5


async def async_set_position(
    client: Client,
    current_position: int,
    target_position: int,
    open_curve: CalibrationCurve | None,
    close_curve: CalibrationCurve | None,
) -> DoorStatus:
    """Drive the door to approximately the target position."""
    status = await _move_toward(
        client, current_position, target_position, open_curve, close_curve
    )
    _LOGGER.debug(
        "First move toward %s from %s landed at %s",
        target_position,
        current_position,
        status.position,
    )

    if abs(status.position - target_position) > TOLERANCE:
        status = await _move_toward(
            client, status.position, target_position, open_curve, close_curve
        )
        _LOGGER.debug("Correction move landed at %s", status.position)

    return status


async def _move_toward(
    client: Client,
    current_position: int,
    target_position: int,
    open_curve: CalibrationCurve | None,
    close_curve: CalibrationCurve | None,
) -> DoorStatus:
    """Run one estimated-duration move toward target_position."""
    if current_position == target_position:
        return await async_wait_until_stopped(client)

    opening = target_position > current_position
    curve = open_curve if opening else close_curve

    if curve is not None:
        duration = abs(curve.time_at(target_position) - curve.time_at(current_position))
        await async_send_direction(client, opening=opening)
    else:
        await async_send_direction(client, opening=opening)
        # Sample the hub's live rate shortly after it actually starts moving
        # (a stopped door always reports rate=0, so this can't be read from
        # the pre-move status).
        await asyncio.sleep(STEP_STARTUP_DELAY)
        moving_status = await client.async_get_status()
        rate = abs(moving_status.rate) or FALLBACK_RATE
        duration = max(
            0.0,
            abs(target_position - current_position) / rate - STEP_STARTUP_DELAY,
        )

    _LOGGER.debug(
        "Moving %s from %s to %s, sleeping %.2fs",
        "open" if opening else "close",
        current_position,
        target_position,
        duration,
    )
    await asyncio.sleep(duration)
    await client.async_stop()
    return await async_wait_until_stopped(client)
