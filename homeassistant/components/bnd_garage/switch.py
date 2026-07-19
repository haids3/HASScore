"""Switch platform for the B&D Garage integration: lockout and auxiliary controls."""

from typing import Any, override

from bnd_garage_client.errors import (
    AuthenticationError,
    HubCommandError,
    HubUnreachableError,
)

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BndGarageConfigEntry, BndGarageDataUpdateCoordinator
from .entity import BndGarageEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BndGarageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up lockout/auxiliary switches for each device, for whichever it reports."""
    entities: list[SwitchEntity] = []
    for coordinator in entry.runtime_data:
        if coordinator.data.remote_control_lockout is not None:
            entities.append(BndGarageRemoteControlLockoutSwitch(coordinator))
        if coordinator.data.phone_lockout is not None:
            entities.append(BndGaragePhoneLockoutSwitch(coordinator))
        if coordinator.data.auxiliary is not None:
            entities.append(BndGarageAuxiliarySwitch(coordinator))
    async_add_entities(entities)


class BndGarageRemoteControlLockoutSwitch(BndGarageEntity, SwitchEntity):
    """Switch to lock out physical remotes and wall buttons.

    Has no effect on app-protocol control - only physical remotes/buttons.
    """

    _attr_translation_key = "remote_control_lockout"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BndGarageDataUpdateCoordinator) -> None:
        """Initialize with a title-independent unique_id suffix."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._attr_unique_id}_remote_control_lockout"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether remote-control lockout is currently enabled."""
        lockout = self.coordinator.data.remote_control_lockout
        return lockout.is_on if lockout is not None else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable remote-control lockout."""
        await self._async_set_state(enabled=True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable remote-control lockout."""
        await self._async_set_state(enabled=False)

    async def _async_set_state(self, *, enabled: bool) -> None:
        lockout = self.coordinator.data.remote_control_lockout
        if lockout is None or lockout.is_on == enabled:
            return
        try:
            await self.coordinator.set_remote_control_lockout(enabled)
        except (HubCommandError, AuthenticationError, HubUnreachableError) as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()


class BndGaragePhoneLockoutSwitch(BndGarageEntity, SwitchEntity):
    """Switch to lock out app-protocol control (open/close/stop/etc).

    Status reads keep working regardless. Turning this back off is never
    itself blocked by the lockout, so there's no risk of this integration
    locking itself out permanently - only of a real remote (this one, the
    vendor app, any other paired phone) losing control until it's off again.
    """

    _attr_translation_key = "phone_lockout"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BndGarageDataUpdateCoordinator) -> None:
        """Initialize with a title-independent unique_id suffix."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._attr_unique_id}_phone_lockout"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether phone lockout is currently enabled."""
        lockout = self.coordinator.data.phone_lockout
        return lockout.is_on if lockout is not None else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable phone lockout."""
        await self._async_set_state(enabled=True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable phone lockout."""
        await self._async_set_state(enabled=False)

    async def _async_set_state(self, *, enabled: bool) -> None:
        lockout = self.coordinator.data.phone_lockout
        if lockout is None or lockout.is_on == enabled:
            return
        try:
            await self.coordinator.set_phone_lockout(enabled)
        except (HubCommandError, AuthenticationError, HubUnreachableError) as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()


class BndGarageAuxiliarySwitch(BndGarageEntity, SwitchEntity):
    """Switch for the hub's auxiliary relay output.

    A generic relay slot - what it actually drives depends on how the
    installer wired it (an accessory light, a vent fan, etc). Requires the
    hub's auxiliary output duration (`PARAM_AUX_OUTPUT_TIME_SEC`) to be set
    to a nonzero value in the vendor app - at 0 seconds the relay accepts
    commands but shows no observable effect, which is what made it look
    unwired/broken before this was understood.
    """

    _attr_translation_key = "auxiliary"

    def __init__(self, coordinator: BndGarageDataUpdateCoordinator) -> None:
        """Initialize with a title-independent unique_id suffix."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._attr_unique_id}_auxiliary"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the auxiliary relay is currently on."""
        auxiliary = self.coordinator.data.auxiliary
        return auxiliary.is_on if auxiliary is not None else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the auxiliary relay on."""
        await self._async_set_state(want_on=True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the auxiliary relay off."""
        await self._async_set_state(want_on=False)

    async def _async_set_state(self, *, want_on: bool) -> None:
        auxiliary = self.coordinator.data.auxiliary
        if auxiliary is None or auxiliary.is_on == want_on:
            return
        try:
            await self.coordinator.send_command(auxiliary.command)
        except (HubCommandError, AuthenticationError, HubUnreachableError) as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
