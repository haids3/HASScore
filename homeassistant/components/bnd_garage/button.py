"""Button platform for the B&D Garage integration."""

from typing import override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BndGarageConfigEntry
from .entity import BndGarageEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BndGarageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the B&D Garage calibration button."""
    async_add_entities([BndGarageCalibrateButton(entry.runtime_data)])


class BndGarageCalibrateButton(BndGarageEntity, ButtonEntity):
    """Button that measures the door's real open/close travel curve.

    Drives the door through one open pass and one close pass, so pressing
    it moves the physical door - it isn't harmless like most config buttons.
    """

    _attr_translation_key = "calibrate"
    _attr_entity_category = EntityCategory.CONFIG

    @override
    async def async_press(self) -> None:
        """Run travel-time calibration."""
        await self.coordinator.async_calibrate()
