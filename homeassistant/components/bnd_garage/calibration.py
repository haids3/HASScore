"""Travel-time calibration data model for the B&D Garage integration.

Real garage doors decelerate near their open/closed limits, so a single
average rate (what DataUpdateCoordinator falls back to when uncalibrated)
isn't accurate there. The coordinator passively times ordinary full-range
open/close movements during regular use and calls build_curve() to turn
that single measured total time into a standard-shaped curve: the first
and last EDGE_DISTANCE_FRACTION of travel at EDGE_SPEED_FACTOR times the
average rate (motor soft-start ramp-up, and mechanical deceleration
approaching the limit), the middle faster to match.

This is a deliberate assumption, not a per-installation measurement of the
actual shape. Sampling true intermediate position by stopping the door
mid-travel was tried and confirmed to backfire: each stop/restart
re-triggers the motor's own soft-start ramp-up, so a curve built that way
measured travel as ~60% slower than reality. The standard-shape assumption
trades shape precision (not obtainable cleanly anyway) for not corrupting
the one number that matters most: total time.

This curve only applies to ordinary open/close, where the hub genuinely
does freeze `position` at the start value until the door settles - live
positioning to an exact target (`HubClient.set_open_percent`) is a
different hub-native command that reports real progress throughout and
needs no client-side estimate at all (confirmed live: `coordinator.py`
prefers the hub's own value whenever it's actually advancing). The original
finding that drove this whole approach - needing accuracy this method
can't deliver for driving to a specific position - no longer applies to
positioning at all now that a hub-native command exists for it; it only
ever applied to plain open/close's *displayed* estimate while moving.
"""

from dataclasses import dataclass
from itertools import pairwise
from typing import Self

EDGE_DISTANCE_FRACTION = 0.10
EDGE_SPEED_FACTOR = 0.5


@dataclass(frozen=True)
class CalibrationCurve:
    """Measured (elapsed_seconds, position) points for one travel direction."""

    points: tuple[tuple[float, int], ...]

    def position_at(self, elapsed: float) -> int:
        """Interpolate position at the given elapsed time from measured points."""
        points = self.points
        if elapsed <= points[0][0]:
            return points[0][1]
        for (t0, p0), (t1, p1) in pairwise(points):
            if elapsed <= t1:
                if t1 == t0:
                    return p1
                fraction = (elapsed - t0) / (t1 - t0)
                return round(p0 + (p1 - p0) * fraction)
        return points[-1][1]

    def to_json(self) -> list[list[float]]:
        """Serialize for storage in config entry options."""
        return [[t, p] for t, p in self.points]

    @classmethod
    def from_json(cls, data: list[list[float]] | None) -> Self | None:
        """Deserialize from config entry options; None if never calibrated."""
        if not data:
            return None
        return cls(points=tuple((t, int(p)) for t, p in data))


def build_curve(
    start_position: int, end_position: int, total_time: float
) -> CalibrationCurve:
    """Build a standard-shaped curve from one measured continuous movement."""
    distance = end_position - start_position
    edge_distance = distance * EDGE_DISTANCE_FRACTION
    edge_time = total_time * EDGE_DISTANCE_FRACTION / EDGE_SPEED_FACTOR

    points = (
        (0.0, start_position),
        (edge_time, round(start_position + edge_distance)),
        (total_time - edge_time, round(end_position - edge_distance)),
        (total_time, end_position),
    )
    return CalibrationCurve(points=points)
