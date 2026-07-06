"""Describe logbook events for the B&D Garage integration."""

from collections.abc import Callable

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_ACTIVITY


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe logbook events."""

    @callback
    def async_describe_activity_event(event: Event) -> dict[str, str]:
        """Describe a B&D Garage activity event.

        `event.data["text"]` already comes fully formed from the hub with
        attribution baked in, e.g. "Light off by HomeAssistant".
        """
        return {
            LOGBOOK_ENTRY_NAME: "B&D Garage",
            LOGBOOK_ENTRY_MESSAGE: event.data["text"],
        }

    async_describe_event(DOMAIN, EVENT_ACTIVITY, async_describe_activity_event)
