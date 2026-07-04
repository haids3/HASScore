"""Low-level hub control shared by calibration and set-position.

The hub only supports open/close/stop and reports position solely at rest,
never mid-travel - both calibration.py's step sweeps and set_position.py's
estimated-duration moves are built out of the same primitives: send a
direction, wait for the hub to confirm it's actually stopped.
"""

import asyncio
import time

from bnd_garage_api import Client, DoorState, DoorStatus

SETTLE_TIMEOUT = 30.0
"""Max time to wait for the hub to report the door has stopped moving.

Confirmed against real hardware: a full close takes ~19-20s on this door,
longer than the 15s this was originally set to (that value was fine back
when every wait was for a ~10% step, not a full continuous range - it just
never got revisited when calibration.py switched to timing full moves).
Too short a value here doesn't fail loudly - async_wait_until_stopped just
returns whatever stale status it last polled while the door was still
genuinely moving, which looks exactly like the door not responding to a
command at all. Comfortable margin above the slowest direction measured.
"""
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
