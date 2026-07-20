"""DataUpdateCoordinator for the B&D Garage integration."""

from dataclasses import replace
from datetime import timedelta
import logging
import time
from typing import override

from bnd_garage_client import DoorState, HubClient, HubStatus
from bnd_garage_client.errors import AuthenticationError, HubUnreachableError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICES
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
CONF_PRESET_POSITIONS = "preset_positions"

type BndGarageConfigEntry = ConfigEntry[list[BndGarageDataUpdateCoordinator]]


class BndGarageDataUpdateCoordinator(DataUpdateCoordinator[HubStatus]):
    """Coordinator that polls the hub for one device's current door status.

    A hub with multiple door openers gets one of these per device, all
    sharing the same `HubClient`/config entry - see `__init__.py`.
    """

    config_entry: BndGarageConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: BndGarageConfigEntry,
        client: HubClient,
        device_id: str,
    ) -> None:
        """Initialize the coordinator for one device on the hub."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{device_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.device_id = device_id
        self._estimated_position: float = 0
        self._last_estimate_at: float | None = None
        self._last_rate = 0.0
        self._segment_started_at: float | None = None
        self._segment_is_opening: bool | None = None
        self._segment_start_position: float = 0
        self._segment_start_raw_position: int | None = None
        self._pending_preset_cmd: int | None = None
        device_options = config_entry.options.get(CONF_DEVICES, {}).get(device_id, {})
        self.open_curve = CalibrationCurve.from_json(
            device_options.get(CONF_OPEN_CURVE)
        )
        self.close_curve = CalibrationCurve.from_json(
            device_options.get(CONF_CLOSE_CURVE)
        )
        self._preset_positions: dict[int, int] = {
            int(cmd): position
            for cmd, position in device_options.get(CONF_PRESET_POSITIONS, {}).items()
        }

    async def open_door(self) -> None:
        """Open this device's garage door."""
        await self.client.open_door(self.device_id)

    async def close_door(self) -> None:
        """Close this device's garage door."""
        await self.client.close_door(self.device_id)

    async def stop_door(self) -> None:
        """Stop this device's garage door mid-travel."""
        await self.client.stop_door(self.device_id)

    async def set_open_percent(self, percent: int) -> None:
        """Move this device's door to an exact percent-open position."""
        await self.client.set_open_percent(self.device_id, percent)

    async def set_remote_control_lockout(self, enabled: bool) -> None:
        """Enable/disable this device's physical remote/wall-button lockout."""
        await self.client.set_remote_control_lockout(self.device_id, enabled)

    async def set_phone_lockout(self, enabled: bool) -> None:
        """Enable/disable this device's app-protocol control lockout."""
        await self.client.set_phone_lockout(self.device_id, enabled)

    async def send_command(self, command: int) -> None:
        """Send a raw command code to this device (light toggle, aux relay)."""
        await self.client.send_command(self.device_id, command)

    def _update_device_options(self, **updates: object) -> None:
        """Merge `updates` into this device's slice of the config entry options."""
        devices = {
            key: dict(value)
            for key, value in self.config_entry.options.get(CONF_DEVICES, {}).items()
        }
        devices[self.device_id] = {**devices.get(self.device_id, {}), **updates}
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={**self.config_entry.options, CONF_DEVICES: devices},
        )

    @override
    async def _async_update_data(self) -> HubStatus:
        """Fetch this device's current status from the hub."""
        try:
            status = await self.client.get_status(self.device_id)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except HubUnreachableError as err:
            raise UpdateFailed(str(err)) from err

        if status.state == DoorState.MOVING:
            self._advance_position_estimate(status)
            if status.position != self._segment_start_raw_position:
                # A door genuinely frozen mid-travel (ordinary open/close)
                # only ever reports the position it started this movement
                # from while MOVING. Anything else means the hub is
                # live-tracking this specific movement (e.g. a percent-open
                # target) - trust its own value directly rather than our
                # estimate.
                self._estimated_position = status.position
            estimated = round(min(99, max(1, self._estimated_position)))
            status = replace(status, position=estimated)
        else:
            self._maybe_auto_calibrate(status.position)
            self._maybe_record_preset_position(status.position)
            # Trust the hub's own reported position once it confirms it's at rest.
            self._estimated_position = status.position
            self._segment_started_at = None
            self._segment_is_opening = None
            self._segment_start_raw_position = None
            self._last_estimate_at = None

        self.update_interval = (
            MOVING_UPDATE_INTERVAL
            if status.state == DoorState.MOVING
            else UPDATE_INTERVAL
        )
        return status

    def _advance_position_estimate(self, status: HubStatus) -> None:
        """Advance the position estimate for one poll while moving.

        Uses a calibrated travel curve (see calibration.py) when one covers
        this movement - i.e. calibration has been run and this leg started
        from the extreme the curve was measured from - otherwise falls back
        to a flat estimate from the hub's own reported rate.

        This estimate is only actually used by the caller when the hub isn't
        already live-tracking the movement itself - the caller detects that
        by comparing the hub's raw position against `_segment_start_raw_position`
        (set below): an ordinary open/close freezes `position` at whatever
        value the door started this movement from until it settles, but a
        percent-open move reports real progress throughout. Always run this
        regardless, so the estimate machinery (and its segment/rate
        bookkeeping) stays current in case a movement's raw position does
        turn out to be frozen.
        """
        now = time.monotonic()
        is_opening = status.rate > 0

        if self._segment_started_at is None or is_opening != self._segment_is_opening:
            self._segment_started_at = now
            self._segment_is_opening = is_opening
            self._segment_start_position = self._estimated_position
            self._segment_start_raw_position = status.position

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

        self._update_device_options(
            open_curve=self.open_curve.to_json() if self.open_curve else None,
            close_curve=self.close_curve.to_json() if self.close_curve else None,
        )

    def _maybe_record_preset_position(self, end_position: int) -> None:
        """Remember where the door settled after a preset (e.g. Pet) was used.

        A preset's target position is configured in the vendor app and isn't
        included in the hub's own aux listing, so the only way to know it is
        to trigger the preset and see where the door ends up. Only reliable
        if nothing else redirects the door before it settles - acceptable
        since presets are a one-shot, uninterrupted action in normal use.
        """
        if self._pending_preset_cmd is None:
            return
        self._preset_positions[self._pending_preset_cmd] = end_position
        self._pending_preset_cmd = None
        self._update_device_options(
            preset_positions={
                str(cmd): position for cmd, position in self._preset_positions.items()
            }
        )

    def preset_position(self, cmd: int) -> int | None:
        """Return the last observed settled position for a preset, if known."""
        return self._preset_positions.get(cmd)

    async def async_activate_preset(self, cmd: int) -> None:
        """Trigger a hub preset (e.g. a position preset) and refresh status.

        Relies on the immediate refresh already seeing the door as MOVING
        (confirmed live: the hub reports a nonzero rate as soon as
        send_command returns) - otherwise this poll would record the
        pre-move position as the preset's target instead of waiting for it
        to settle.
        """
        await self.send_command(cmd)
        self._pending_preset_cmd = cmd
        await self.async_request_refresh()
