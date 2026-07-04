"""Cover platform for the B&D Garage integration."""

from collections.abc import Awaitable, Callable
from typing import Any, override

from bnd_garage_api.exceptions import CannotConnect, HubCommandError, InvalidAuth
from bnd_garage_api.models import DoorState

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BndGarageConfigEntry
from .entity import BndGarageEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BndGarageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the B&D Garage cover."""
    async_add_entities([BndGarageCover(entry.runtime_data)])


class BndGarageCover(BndGarageEntity, CoverEntity):
    """Representation of a B&D garage door."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    _attr_name = None

    @property
    @override
    def current_cover_position(self) -> int | None:
        """Return the current position of the door, 0 (closed) to 100 (open)."""
        if self.coordinator.data.state == DoorState.UNKNOWN:
            return None
        return self.coordinator.data.position

    @property
    @override
    def is_closed(self) -> bool | None:
        """Return if the door is closed, or None if the hub reported no position."""
        if self.coordinator.data.state == DoorState.UNKNOWN:
            return None
        return self.coordinator.data.state == DoorState.CLOSED

    @property
    @override
    def is_opening(self) -> bool:
        """Return if the door is currently opening."""
        return (
            self.coordinator.data.state == DoorState.MOVING
            and self.coordinator.data.rate > 0
        )

    @property
    @override
    def is_closing(self) -> bool:
        """Return if the door is currently closing."""
        return (
            self.coordinator.data.state == DoorState.MOVING
            and self.coordinator.data.rate < 0
        )

    @override
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the garage door."""
        await self._async_send_command(self.coordinator.client.async_open)

    @override
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the garage door."""
        await self._async_send_command(self.coordinator.client.async_close_door)

    @override
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the garage door."""
        await self._async_send_command(self.coordinator.client.async_stop)

    async def _async_send_command(self, command: Callable[[], Awaitable[None]]) -> None:
        try:
            await command()
        except (HubCommandError, CannotConnect, InvalidAuth) as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
