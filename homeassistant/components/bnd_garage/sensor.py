"""Sensor platform for the B&D Garage integration: the hub's activity log."""

from typing import override

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BndGarageConfigEntry
from .entity import BndGarageEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BndGarageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the B&D Garage activity sensor, if the hub reports one."""
    if entry.runtime_data.data.activity is not None:
        async_add_entities([BndGarageActivitySensor(entry.runtime_data)])


class BndGarageActivitySensor(BndGarageEntity, SensorEntity):
    """The hub's own record of the most recent action and who performed it."""

    _attr_translation_key = "last_activity"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    @override
    def native_value(self) -> str | None:
        """Return the hub's own description of the last action."""
        activity = self.coordinator.data.activity
        return activity.text if activity is not None else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, int] | None:
        """Return the log entry's timestamp and alert code."""
        activity = self.coordinator.data.activity
        if activity is None:
            return None
        return {"logged_at": activity.logged_at, "alert": activity.alert}
