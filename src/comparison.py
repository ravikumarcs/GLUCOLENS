"""Build a structured current-vs-recommended pump settings comparison.

Format-independent: both the CLI (text) and the web UI (tables) render this
same structure, so the comparison logic itself only lives in one place.
"""

from typing import Dict, List, Optional


def _at(hourly: dict, hour: int):
    """Look up an hourly value, tolerating int or string keys (a
    recommendation dict fresh from the engine uses int keys; one round-tripped
    through JSON uses strings)."""
    return hourly.get(hour, hourly.get(str(hour)))


def compare_settings(current: dict, recommendation: dict) -> Dict[str, List[dict]]:
    """Compare a currently-configured pump settings dict (schema: see
    data/sample_current_settings.json) against an OmnipodSettings.to_dict()
    (or the "recommendations" sub-dict of a full report).

    Returns:
        {
          "scalars": [{"label", "unit", "current", "recommended"}, ...],
          "basal_segments": [{"hour", "current", "recommended"}, ...],
          "isf_segments": [{"hour", "current", "recommended"}, ...],
          "carb_ratio_segments": [{"hour", "current", "recommended"}, ...],
          "target_segments": [{"hour", "current", "recommended_correction_target"}, ...],
        }
    """
    rec_rates = recommendation.get("basal_profile", {}).get("rates", {})
    rec_factors = recommendation.get("insulin_sensitivity_factor", {}).get("factors", {})
    rec_ratios = recommendation.get("carb_ratio", {}).get("ratios", {})

    scalars = [
        {
            "label": "Max Basal", "unit": "units/hr",
            "current": current.get("max_basal"),
            "recommended": recommendation.get("max_basal"),
        },
        {
            "label": "Max Bolus", "unit": "units",
            "current": current.get("max_bolus"),
            "recommended": recommendation.get("max_bolus"),
        },
        {
            "label": "Active Insulin Time", "unit": "hours",
            "current": current.get("active_insulin_time"),
            "recommended": recommendation.get("active_insulin_time"),
        },
    ]

    basal_segments = [
        {
            "hour": int(seg["start_hour"]),
            "current": seg["rate"],
            "recommended": _at(rec_rates, int(seg["start_hour"])),
        }
        for seg in current.get("basal_segments") or []
    ]

    isf_segments = [
        {
            "hour": int(seg["start_hour"]),
            "current": seg["value"],
            "recommended": _at(rec_factors, int(seg["start_hour"])),
        }
        for seg in current.get("isf_segments") or []
    ]

    carb_ratio_segments = [
        {
            "hour": int(seg["start_hour"]),
            "current": seg["value"],
            "recommended": _at(rec_ratios, int(seg["start_hour"])),
        }
        for seg in current.get("carb_ratio_segments") or []
    ]

    target_segments = [
        {
            "hour": int(seg["start_hour"]),
            "current": seg["target"],
            "recommended_correction_target": recommendation.get("correction_target"),
        }
        for seg in current.get("target_segments") or []
    ]

    return {
        "scalars": scalars,
        "basal_segments": basal_segments,
        "isf_segments": isf_segments,
        "carb_ratio_segments": carb_ratio_segments,
        "target_segments": target_segments,
    }
