"""DataUpdateCoordinator for the B&D Garage integration."""

from dataclasses import replace
from datetime import timedelta
import logging
import time
from typing import override

from bnd_garage_api import Client, DoorState, DoorStatus
from bnd_garage_api.exceptions import CannotConnect, InvalidAuth

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=10)
MOVING_UPDATE_INTERVAL = timedelta(seconds=2)

type BndGarageConfigEntry = ConfigEntry[BndGarageDataUpdateCoordinator]


class BndGarageDataUpdateCoordinator(DataUpdateCoordinator[DoorStatus]):
    """Coordinator that polls the hub for the current door status."""

    config_entry: BndGarageConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: BndGarageConfigEntry, client: Client
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._move_started_at: float | None = None
        self._move_started_position: float = 0
        self._move_rate = 0.0

    @override
    async def _async_update_data(self) -> DoorStatus:
        """Fetch the current door status from the hub."""
        try:
            status = await self.client.async_get_status()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            raise UpdateFailed(str(err)) from err

        if status.state == DoorState.MOVING:
            status = replace(status, position=self._estimate_moving_position(status))
        else:
            self._move_started_at = None
            self._move_started_position = status.position

        self.update_interval = (
            MOVING_UPDATE_INTERVAL
            if status.state == DoorState.MOVING
            else UPDATE_INTERVAL
        )
        return status

    def _estimate_moving_position(self, status: DoorStatus) -> int:
        """Extrapolate position from elapsed time and rate.

        The hub only reports the last at-rest position while actually moving
        (confirmed against real hardware - position stays pinned at 0/100 for
        the whole ~15s travel, then jumps straight to the final value), so we
        estimate it locally instead of showing a stale number.
        """
        now = time.monotonic()
        if self._move_started_at is None:
            self._move_started_at = now
            self._move_rate = status.rate
        elif (status.rate > 0) != (self._move_rate > 0):
            # Direction reversed mid-travel (e.g. an obstruction safety-reverse) -
            # re-anchor from wherever we'd estimated we were, not the position
            # from before this whole movement sequence started.
            self._move_started_position = self._raw_position_estimate(now)
            self._move_started_at = now
            self._move_rate = status.rate

        return round(min(99, max(1, self._raw_position_estimate(now))))

    def _raw_position_estimate(self, now: float) -> float:
        """Return the unclamped estimated position at the given monotonic time."""
        assert self._move_started_at is not None
        elapsed = now - self._move_started_at
        return self._move_started_position + self._move_rate * elapsed
