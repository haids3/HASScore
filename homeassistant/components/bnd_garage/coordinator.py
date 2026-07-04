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
        self._estimated_position: float = 0
        self._last_estimate_at: float | None = None
        self._last_rate = 0.0

    @override
    async def _async_update_data(self) -> DoorStatus:
        """Fetch the current door status from the hub."""
        try:
            status = await self.client.async_get_status()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            raise UpdateFailed(str(err)) from err

        self._advance_position_estimate(status.rate)

        if status.state == DoorState.MOVING:
            estimated = round(min(99, max(1, self._estimated_position)))
            status = replace(status, position=estimated)
        else:
            # Trust the hub's own reported position once it confirms it's at rest.
            self._estimated_position = status.position

        self.update_interval = (
            MOVING_UPDATE_INTERVAL
            if status.state == DoorState.MOVING
            else UPDATE_INTERVAL
        )
        return status

    def _advance_position_estimate(self, rate: float) -> None:
        """Fold in elapsed time at the previous rate, then adopt the new one.

        The hub only reports the last at-rest position while actually
        moving, so we extrapolate locally instead. Re-adopting the rate on
        every poll (not just once when movement starts) means a rate change
        mid-travel - drift, or an obstruction safety-reverse - is picked up
        within one poll interval rather than compounding a stale rate.
        """
        now = time.monotonic()
        if self._last_estimate_at is not None:
            elapsed = now - self._last_estimate_at
            self._estimated_position += self._last_rate * elapsed
        self._last_estimate_at = now
        self._last_rate = rate
