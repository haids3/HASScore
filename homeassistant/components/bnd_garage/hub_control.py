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

COMMAND_SETTLE_DELAY = 1.0
"""Minimum gap enforced before sending a command that follows another one.

Defensive only - NOT confirmed to fix anything. Real hardware testing found
a reproducible failure where a close command sent right after an open
movement just completed doesn't move the door at all (3/3 attempts, with
this same 1s delay in place each time), while the reverse (open right after
a close) and same-direction retries both work fine. That specific failure
is still open and unresolved; this delay is kept as a generally-reasonable
precaution for these automated multi-command sequences, not as a fix for
it. See DEVELOPMENT_NOTES.md / session history for the full investigation.
"""


async def async_send_direction(client: Client, *, opening: bool) -> None:
    """Send the open or close command for the given direction."""
    await asyncio.sleep(COMMAND_SETTLE_DELAY)
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
