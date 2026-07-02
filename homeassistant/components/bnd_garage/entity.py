"""Base entity for the B&D Garage integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BndGarageDataUpdateCoordinator


class BndGarageEntity(CoordinatorEntity[BndGarageDataUpdateCoordinator]):
    """Common base for B&D Garage entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BndGarageDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        hub_id = coordinator.config_entry.unique_id
        assert hub_id is not None
        self._attr_unique_id = hub_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub_id)},
            name="B&D Garage",
            manufacturer="B&D",
        )
