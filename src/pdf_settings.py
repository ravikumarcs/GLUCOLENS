"""Best-effort parser for the 'Devices' page of a Glooko PDF report.

Extracts the currently-configured pump settings (Active Insulin Time, Max
Basal, Max Bolus, Min BG for Bolus Calc, and the segmented Basal Rate / ISF /
Carb Ratio / BG Target Range tables) into the same schema used by
data/sample_current_settings.json, so a caregiver can upload the PDF Glooko
already gives them instead of hand-transcribing settings.

Text layout varies across Glooko report versions and pump models; if a
section can't be found, it's simply omitted from the result rather than
raising. Treat the output as a best-effort starting point to review, not a
guaranteed-complete or guaranteed-correct parse -- always sanity-check the
extracted values against the PDF itself before relying on them.
"""

import re
from datetime import datetime
from typing import Dict, List

import pypdf


# Matches a segment row like "12:00 AM \n(2 hr)\n160 mg/dL" or, for BG target
# ranges, "12:00 AM \n(2 hr)\n130 (+0/-0) mg/dL".
_SEGMENT_RE = re.compile(
    r'(\d{1,2}:\d{2}\s*[AP]M)\s*\n\((\d+)\s*hr\)\n([\d.]+)\s*(?:\([^)]*\)\s*)?(Units/hr|mg/dL|g/Unit)'
)


def _time_to_hour(time_str: str) -> int:
    return datetime.strptime(time_str.strip(), "%I:%M %p").hour


def _extract_segments(section_text: str, expected_unit: str) -> List[Dict]:
    segments = []
    for match in _SEGMENT_RE.finditer(section_text):
        time_str, _duration, value_str, unit = match.groups()
        if unit != expected_unit:
            continue
        segments.append({"start_hour": _time_to_hour(time_str), "value": float(value_str)})
    return segments


def parse_settings_from_text(text: str) -> Dict:
    """Parse pump settings out of the extracted text of a Glooko 'Devices' page."""
    settings: Dict = {}

    match = re.search(r'Active Insulin Time\s*\n\s*([\d.]+)\s*h\b', text)
    if match:
        settings["active_insulin_time"] = float(match.group(1))

    match = re.search(r'Max basal rate\s*\n\s*([\d.]+)\s*Units/hr', text)
    if match:
        settings["max_basal"] = float(match.group(1))

    match = re.search(r'Max Bolus\s*\n\s*([\d.]+)\s*U\b', text)
    if match:
        settings["max_bolus"] = float(match.group(1))

    min_bg_match = re.search(r'Min BG for Bolus Calc\s*\n\s*([\d.]+)\s*mg/dL', text)
    if min_bg_match:
        settings["min_bg_for_bolus_calc"] = float(min_bg_match.group(1))

    isf_idx = text.find("Sensitivity (ISF")
    cr_idx = text.find("Insulin: Carb Ratios")
    target_idx = text.find("BG Target Range")
    correction_idx = text.find("BG Correction Threshold")

    basal_section_start = min_bg_match.end() if min_bg_match else 0
    basal_section_end = isf_idx if isf_idx != -1 else len(text)
    basal_segments = _extract_segments(text[basal_section_start:basal_section_end], "Units/hr")
    if basal_segments:
        settings["basal_segments"] = [
            {"start_hour": s["start_hour"], "rate": s["value"]} for s in basal_segments
        ]

    if isf_idx != -1:
        isf_section_end = cr_idx if cr_idx != -1 else len(text)
        isf_segments = _extract_segments(text[isf_idx:isf_section_end], "mg/dL")
        if isf_segments:
            settings["isf_segments"] = [
                {"start_hour": s["start_hour"], "value": s["value"]} for s in isf_segments
            ]

    if cr_idx != -1:
        cr_section_end = target_idx if target_idx != -1 else len(text)
        cr_segments = _extract_segments(text[cr_idx:cr_section_end], "g/Unit")
        if cr_segments:
            settings["carb_ratio_segments"] = [
                {"start_hour": s["start_hour"], "value": s["value"]} for s in cr_segments
            ]

    if target_idx != -1:
        target_section_end = correction_idx if correction_idx != -1 else len(text)
        target_segments = _extract_segments(text[target_idx:target_section_end], "mg/dL")
        if target_segments:
            settings["target_segments"] = [
                {"start_hour": s["start_hour"], "target": s["value"]} for s in target_segments
            ]

    return settings


def parse_glooko_pdf(file) -> Dict:
    """Parse settings from a Glooko PDF report.

    `file` may be a path or a file-like object (e.g. a Streamlit
    UploadedFile / BytesIO).
    """
    reader = pypdf.PdfReader(file)
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return parse_settings_from_text(full_text)
