"""Cover platform for the B&D Garage integration."""

from collections.abc import Awaitable, Callable
from typing import Any, override

from bnd_garage_client.const import (
    PERCENT_OPEN_MAX,
    PERCENT_OPEN_MIN,
    PERCENT_OPEN_STEP,
)
from bnd_garage_client.errors import (
    AuthenticationError,
    HubCommandError,
    HubUnreachableError,
)
from bnd_garage_client.models import DoorState

from homeassistant.components.cover import (
    ATTR_POSITION,
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


def _round_to_percent_step(target: int) -> int:
    """Round an arbitrary 0-100 target to the nearest step the hub supports.

    The hub's percent-open command only accepts multiples of
    `PERCENT_OPEN_STEP` within `[PERCENT_OPEN_MIN, PERCENT_OPEN_MAX]` - a
    coarser 5% granularity than the slider itself, which reports/accepts any
    integer 0-100. Full 0/100 targets are handled separately by the caller
    (a full close/open, not a percent-open command at all).
    """
    rounded = round(target / PERCENT_OPEN_STEP) * PERCENT_OPEN_STEP
    return max(PERCENT_OPEN_MIN, min(PERCENT_OPEN_MAX, rounded))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BndGarageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a cover for each device the hub reports."""
    async_add_entities(
        BndGarageCover(coordinator) for coordinator in entry.runtime_data
    )


class BndGarageCover(BndGarageEntity, CoverEntity):
    """Representation of a B&D garage door."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
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
        await self._async_send_command(self.coordinator.open_door)

    @override
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the garage door."""
        await self._async_send_command(self.coordinator.close_door)

    @override
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the garage door."""
        await self._async_send_command(self.coordinator.stop_door)

    @override
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the door to a specific position.

        0 and 100 map to a full close/open rather than a percent-open
        command - the hub's percent-open range is 5-95 only. Anything else
        is rounded to the nearest 5% step the hub actually supports.
        """
        target: int = kwargs[ATTR_POSITION]
        if target == 0:
            await self._async_send_command(self.coordinator.close_door)
        elif target == 100:
            await self._async_send_command(self.coordinator.open_door)
        else:
            rounded = _round_to_percent_step(target)
            await self._async_send_command(
                lambda: self.coordinator.set_open_percent(rounded)
            )

    async def _async_send_command(self, command: Callable[[], Awaitable[None]]) -> None:
        try:
            await command()
        except (HubCommandError, AuthenticationError, HubUnreachableError) as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
