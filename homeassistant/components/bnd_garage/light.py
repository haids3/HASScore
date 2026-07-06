"""Light platform for the B&D Garage integration."""

from typing import Any, override

from bnd_garage_client.errors import (
    AuthenticationError,
    HubCommandError,
    HubUnreachableError,
)

from homeassistant.components.light import ColorMode, LightEntity
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
    """Set up the B&D Garage hub light, if the hub reports one."""
    if entry.runtime_data.data.light is not None:
        async_add_entities([BndGarageLight(entry.runtime_data)])


class BndGarageLight(BndGarageEntity, LightEntity):
    """Representation of the hub's light."""

    _attr_translation_key = "hub_light"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the light is currently on."""
        light = self.coordinator.data.light
        return light.is_on if light is not None else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        await self._async_set_state(want_on=True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_set_state(want_on=False)

    async def _async_set_state(self, *, want_on: bool) -> None:
        light = self.coordinator.data.light
        if light is None or light.is_on == want_on:
            return
        try:
            await self.coordinator.client.send_command(light.command)
        except (HubCommandError, AuthenticationError, HubUnreachableError) as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
