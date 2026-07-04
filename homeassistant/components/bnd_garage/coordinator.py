"""DataUpdateCoordinator for the B&D Garage integration."""

from datetime import timedelta
import logging
from typing import override

from bnd_garage_api import Client, DoorStatus
from bnd_garage_api.exceptions import CannotConnect, InvalidAuth

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=10)

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

    @override
    async def _async_update_data(self) -> DoorStatus:
        """Fetch the current door status from the hub."""
        try:
            return await self.client.async_get_status()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            raise UpdateFailed(str(err)) from err
