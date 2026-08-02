"""Tests for parsing pump settings out of a Glooko PDF 'Devices' page.

Uses a synthetic fixture matching the real Glooko text-extraction layout
(observed via pypdf) rather than a real report, both to avoid depending on
a binary PDF fixture and to avoid embedding anyone's real device settings.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_settings import parse_settings_from_text


DEVICES_PAGE_TEXT = """General
Active CGM
Dexcom G7
Active Insulin Time
4 h
Basal
Active basal program
Basal
Max basal rate
1.2 Units/hr
Temporary Basal Enabled
ON
Bolus
Extended Bolus
ON
Max Bolus
6 U
Min BG for Bolus Calc
80 mg/dL
Reverse Correction
OFF
Basal
Basal
Active
Active
12:00 AM
(24 hr)
0.5 Units/hr
Total
12.0 Units
Sensitivity (ISF, Correction)
Profile
Active
Active
12:00 AM
(6 hr)
150 mg/dL
6:00 AM
(6 hr)
100 mg/dL
12:00 PM
(6 hr)
120 mg/dL
6:00 PM
(6 hr)
150 mg/dL
Insulin: Carb Ratios
Profile
Active
Active
12:00 AM
(6 hr)
12 g/Unit
6:00 AM
(6 hr)
8 g/Unit
12:00 PM
(6 hr)
10 g/Unit
6:00 PM
(6 hr)
12 g/Unit
BG Target Range
Profile
Active
Active
12:00 AM
(24 hr)
110 (+0/-0) mg/dL
BG Correction Threshold
Profile
Active
Active
12:00 AM
(24 hr)
110 mg/dL
Test Patient DOB: Jan 1, 2015
"""


class TestParseGlookoPdfSettings(unittest.TestCase):
    def setUp(self):
        self.settings = parse_settings_from_text(DEVICES_PAGE_TEXT)

    def test_scalar_fields(self):
        self.assertEqual(self.settings["active_insulin_time"], 4.0)
        self.assertEqual(self.settings["max_basal"], 1.2)
        self.assertEqual(self.settings["max_bolus"], 6.0)
        self.assertEqual(self.settings["min_bg_for_bolus_calc"], 80.0)

    def test_basal_segments(self):
        self.assertEqual(self.settings["basal_segments"], [{"start_hour": 0, "rate": 0.5}])

    def test_isf_segments(self):
        self.assertEqual(
            self.settings["isf_segments"],
            [
                {"start_hour": 0, "value": 150.0},
                {"start_hour": 6, "value": 100.0},
                {"start_hour": 12, "value": 120.0},
                {"start_hour": 18, "value": 150.0},
            ],
        )

    def test_carb_ratio_segments(self):
        self.assertEqual(
            self.settings["carb_ratio_segments"],
            [
                {"start_hour": 0, "value": 12.0},
                {"start_hour": 6, "value": 8.0},
                {"start_hour": 12, "value": 10.0},
                {"start_hour": 18, "value": 12.0},
            ],
        )

    def test_target_segments_ignore_over_under_annotation(self):
        self.assertEqual(self.settings["target_segments"], [{"start_hour": 0, "target": 110.0}])

    def test_missing_sections_are_simply_omitted(self):
        settings = parse_settings_from_text("Nothing relevant here.")
        self.assertEqual(settings, {})


if __name__ == "__main__":
    unittest.main()
