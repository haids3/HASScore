"""Button platform for the B&D Garage integration: hub position presets."""

from typing import override

from bnd_garage_client.errors import (
    AuthenticationError,
    HubCommandError,
    HubUnreachableError,
)

from homeassistant.components.button import ButtonEntity
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
    """Set up a button for each position preset the hub currently reports."""
    coordinator = entry.runtime_data
    async_add_entities(
        BndGaragePresetButton(coordinator, index, preset.command)
        for index, preset in enumerate(coordinator.data.presets)
    )


class BndGaragePresetButton(BndGarageEntity, ButtonEntity):
    """A button that drives the door to one hub-configured preset position.

    The preset's name and target position are both configured in the vendor
    app and can change at any time, so both are read live from the
    coordinator on every access rather than cached at creation. The
    entity_id is deliberately *not* derived from the (changeable) title -
    otherwise renaming a preset in the app (e.g. Pet -> Ventilation) would
    leave a stale, mismatched entity_id behind permanently, since Home
    Assistant only picks an entity_id once and doesn't rename it.
    """

    def __init__(
        self, coordinator: BndGarageDataUpdateCoordinator, index: int, cmd: int
    ) -> None:
        """Initialize the button for a specific preset command code."""
        super().__init__(coordinator)
        self._cmd = cmd
        self._suggested_object_id = f"partial_{index + 1}"
        self._attr_unique_id = f"{self._attr_unique_id}_preset_{cmd}"

    @property
    @override
    def name(self) -> str | None:
        """Return the preset's current title, as configured in the vendor app."""
        for preset in self.coordinator.data.presets:
            if preset.command == self._cmd:
                return preset.label
        return None

    @property
    @override
    def suggested_object_id(self) -> str | None:
        """Return a stable, title-independent suggested entity_id slug."""
        return self._suggested_object_id

    @property
    @override
    def available(self) -> bool:
        """Return whether the hub still reports this preset."""
        return super().available and any(
            preset.command == self._cmd for preset in self.coordinator.data.presets
        )

    @property
    @override
    def extra_state_attributes(self) -> dict[str, int] | None:
        """Return the last position this preset was observed to settle at."""
        position = self.coordinator.preset_position(self._cmd)
        return {"last_position": position} if position is not None else None

    @override
    async def async_press(self) -> None:
        """Trigger this preset."""
        try:
            await self.coordinator.async_activate_preset(self._cmd)
        except (HubCommandError, AuthenticationError, HubUnreachableError) as err:
            raise HomeAssistantError(str(err)) from err
