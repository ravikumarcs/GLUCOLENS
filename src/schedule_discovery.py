"""Generic time-schedule boundary discovery.

Turns a rough per-hour-of-day directional signal into a small number of
contiguous time segments (a "schedule"). This module knows nothing about
ICR, ISF, or Target BG specifically -- callers build their own per-hour
signal and get back segment boundaries; the actual recommended *value* per
segment is computed separately by pooling evidence across each discovered
block (see OmnipodRecommendationEngine.generate_schedule_proposal).
"""

from typing import Dict, List, Tuple


def discover_schedule(
    hourly_lean: Dict[int, str],
    hourly_n: Dict[int, int],
    max_segments: int = 8,
    min_segment_hours: int = 2,
) -> List[Tuple[int, int]]:
    """Discover contiguous (start_hour, end_hour) segments covering 0-24.

    hourly_lean: hour (0-23) -> a rough per-hour directional label (e.g.
      "raise" / "lower" / "neutral"). Hours missing from the dict are
      treated as "neutral" -- absence of data is not itself a signal to
      place a boundary. This is a weak, single-hour signal used only to
      guide *where* merges make sense; it is not Rule-of-Three-gated
      (callers re-evaluate each final, pooled segment properly).
    hourly_n: hour -> amount of evidence backing that hour's lean, used to
      decide which boundaries are weakest when a forced merge is needed.
    max_segments: hard ceiling, never a target -- if the data only
      supports fewer distinct blocks, fewer are returned.
    min_segment_hours: practical minimum width; segments narrower than
      this get absorbed into a neighbor.

    Returns segment boundaries only, in order, covering the full day.
    """
    blocks = [
        {"start": h, "end": h + 1, "lean": hourly_lean.get(h, "neutral"), "n": hourly_n.get(h, 0)}
        for h in range(24)
    ]

    blocks = _merge_same_lean(blocks)
    blocks = _enforce_min_width(blocks, min_segment_hours)
    blocks = _enforce_max_segments(blocks, max_segments)

    return [(b["start"], b["end"]) for b in blocks]


def _merge_same_lean(blocks: List[Dict]) -> List[Dict]:
    merged = [dict(blocks[0])]
    for b in blocks[1:]:
        if b["lean"] == merged[-1]["lean"]:
            merged[-1]["end"] = b["end"]
            merged[-1]["n"] += b["n"]
        else:
            merged.append(dict(b))
    return merged


def _merge_pair(blocks: List[Dict], i: int) -> List[Dict]:
    """Merge adjacent blocks i and i+1 into one."""
    left, right = blocks[i], blocks[i + 1]
    merged_block = {
        "start": left["start"],
        "end": right["end"],
        "lean": right["lean"] if right["n"] >= left["n"] else left["lean"],
        "n": left["n"] + right["n"],
    }
    return blocks[:i] + [merged_block] + blocks[i + 2:]


def _enforce_min_width(blocks: List[Dict], min_segment_hours: int) -> List[Dict]:
    changed = True
    while changed and len(blocks) > 1:
        changed = False
        for i, b in enumerate(blocks):
            if b["end"] - b["start"] < min_segment_hours:
                blocks = _merge_pair(blocks, i if i < len(blocks) - 1 else i - 1)
                changed = True
                break
    return blocks


def _enforce_max_segments(blocks: List[Dict], max_segments: int) -> List[Dict]:
    while len(blocks) > max_segments:
        # Merge the adjacent pair with the least combined evidence --
        # the weakest, least-supported boundary goes first.
        weakest_i = min(range(len(blocks) - 1), key=lambda i: blocks[i]["n"] + blocks[i + 1]["n"])
        blocks = _merge_pair(blocks, weakest_i)
    return blocks
