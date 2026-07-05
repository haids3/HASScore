"""DataUpdateCoordinator for the B&D Garage integration."""

from dataclasses import replace
from datetime import timedelta
import logging
import time
from typing import override

from bnd_garage_api import Client, DoorState, DoorStatus
from bnd_garage_api.exceptions import CannotConnect, InvalidAuth

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .calibration import CalibrationCurve, build_curve
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=10)
MOVING_UPDATE_INTERVAL = timedelta(seconds=2)

CONF_OPEN_CURVE = "open_curve"
CONF_CLOSE_CURVE = "close_curve"

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
        self._estimated_position: float = 0
        self._last_estimate_at: float | None = None
        self._last_rate = 0.0
        self._segment_started_at: float | None = None
        self._segment_is_opening: bool | None = None
        self._segment_start_position: float = 0
        self.open_curve = CalibrationCurve.from_json(
            config_entry.options.get(CONF_OPEN_CURVE)
        )
        self.close_curve = CalibrationCurve.from_json(
            config_entry.options.get(CONF_CLOSE_CURVE)
        )

    @override
    async def _async_update_data(self) -> DoorStatus:
        """Fetch the current door status from the hub."""
        try:
            status = await self.client.async_get_status()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            raise UpdateFailed(str(err)) from err

        if status.state == DoorState.MOVING:
            self._advance_position_estimate(status)
            estimated = round(min(99, max(1, self._estimated_position)))
            status = replace(status, position=estimated)
        else:
            self._maybe_auto_calibrate(status.position)
            # Trust the hub's own reported position once it confirms it's at rest.
            self._estimated_position = status.position
            self._segment_started_at = None
            self._segment_is_opening = None
            self._last_estimate_at = None

        self.update_interval = (
            MOVING_UPDATE_INTERVAL
            if status.state == DoorState.MOVING
            else UPDATE_INTERVAL
        )
        return status

    def _advance_position_estimate(self, status: DoorStatus) -> None:
        """Advance the position estimate for one poll while moving.

        Uses a calibrated travel curve (see calibration.py) when one covers
        this movement - i.e. calibration has been run and this leg started
        from the extreme the curve was measured from - otherwise falls back
        to a flat estimate from the hub's own reported rate. The hub only
        reports the last at-rest position while actually moving, so either
        way we're extrapolating locally rather than showing a stale number.
        """
        now = time.monotonic()
        is_opening = status.rate > 0

        if self._segment_started_at is None or is_opening != self._segment_is_opening:
            self._segment_started_at = now
            self._segment_is_opening = is_opening
            self._segment_start_position = self._estimated_position

        curve = self.open_curve if is_opening else self.close_curve
        reference = 0 if is_opening else 100

        if curve is not None and self._segment_start_position == reference:
            elapsed = now - self._segment_started_at
            self._estimated_position = curve.position_at(elapsed)
        elif self._last_estimate_at is not None:
            elapsed = now - self._last_estimate_at
            self._estimated_position += self._last_rate * elapsed

        self._last_estimate_at = now
        self._last_rate = status.rate

    def _maybe_auto_calibrate(self, end_position: int) -> None:
        """Passively (re)build a curve from an ordinary full-range movement.

        Every normal full open or full close during regular use gives us a
        real measured total time, which is all a curve needs (see
        calibration.py) - so this keeps the curve current automatically,
        self-correcting for drift (wear, temperature) over time. Only
        applies to a clean single-direction segment that started at a true
        extreme and ended at the other one; a mid-travel reversal already
        resets segment tracking to a non-extreme start position, so it's
        naturally excluded here too.
        """
        if self._segment_started_at is None or self._segment_is_opening is None:
            return
        if self._segment_start_position not in (0, 100):
            return
        expected_end = 100 if self._segment_is_opening else 0
        if end_position != expected_end:
            return

        total_time = time.monotonic() - self._segment_started_at
        curve = build_curve(int(self._segment_start_position), end_position, total_time)
        if self._segment_is_opening:
            self.open_curve = curve
        else:
            self.close_curve = curve

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={
                **self.config_entry.options,
                CONF_OPEN_CURVE: self.open_curve.to_json() if self.open_curve else None,
                CONF_CLOSE_CURVE: self.close_curve.to_json()
                if self.close_curve
                else None,
            },
        )
