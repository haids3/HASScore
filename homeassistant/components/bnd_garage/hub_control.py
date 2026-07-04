"""Low-level hub control shared by calibration and set-position.

The hub only supports open/close/stop and reports position solely at rest,
never mid-travel - both calibration.py's step sweeps and set_position.py's
estimated-duration moves are built out of the same primitives: send a
direction, wait for the hub to confirm it's actually stopped.
"""

import asyncio
import time

from bnd_garage_api import Client, DoorState, DoorStatus

SETTLE_TIMEOUT = 15.0
POLL_INTERVAL = 0.5
FALLBACK_RATE = 7.0


async def async_send_direction(client: Client, *, opening: bool) -> None:
    """Send the open or close command for the given direction."""
    if opening:
        await client.async_open()
    else:
        await client.async_close_door()


async def async_wait_until_stopped(client: Client) -> DoorStatus:
    """Poll until the hub reports the door is no longer moving."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    status = await client.async_get_status()
    while status.state == DoorState.MOVING and time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        status = await client.async_get_status()
    return status
