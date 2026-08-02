"""Helpers for working with time-segmented pump settings (basal/ISF/carb-ratio/
target segments), each of which only carries a start_hour -- the end is
implicitly the next segment's start_hour, wrapping at 24."""

from typing import Dict, List, Tuple


def segment_ranges(segments: List[Dict], key: str = "start_hour") -> List[Tuple[int, int]]:
    """Return (start_hour, end_hour) pairs for each segment, sorted by start.

    end_hour is exclusive and may be >= 24 to represent wraparound (e.g. a
    9pm segment followed by the first segment at midnight becomes (21, 24)).
    """
    hours = sorted(s[key] for s in segments)
    ranges = []
    for i, hour in enumerate(hours):
        end = hours[i + 1] if i + 1 < len(hours) else hours[0] + 24
        ranges.append((hour, end))
    return ranges


def hours_in_range(start: int, end: int) -> List[int]:
    """Expand a (start, end) range (end exclusive, possibly >= 24) into hour-of-day ints."""
    return [h % 24 for h in range(start, end)]
