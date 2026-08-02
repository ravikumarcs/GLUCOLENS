"""Tests for parsing real multi-file Glooko exports."""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_loader import GlookoDataLoader


CGM_CSV = (
    "﻿Name:Test Patient,Date Range:2026-01-01 - 2026-01-02\r\n"
    "Timestamp,CGM Glucose Value (mg/dl),Serial Number\r\n"
    "2026-01-01 08:00,120.0,SERIAL123\r\n"
    "2026-01-01 08:05,124.0,SERIAL123\r\n"
)

BG_CSV = (
    "﻿Name:Test Patient,Date Range:2026-01-01 - 2026-01-02\r\n"
    "Timestamp,Glucose Value (mg/dl),Manual Reading,Serial Number\r\n"
    "2026-01-01 12:00,130.0,M,SERIAL123\r\n"
)

BOLUS_CSV = (
    "﻿Name:Test Patient,Date Range:2026-01-01 - 2026-01-02\r\n"
    "Timestamp,Insulin Type,Blood Glucose Input (mg/dl),Carbs Input (g),"
    "Carbs Ratio,Insulin Delivered (U),Initial Delivery (U),Extended Delivery (U),Serial Number\r\n"
    "2026-01-01 08:10,Normal,120.0,30.0,15.0,2.0,,,SERIAL123\r\n"
    "2026-01-01 13:00,Normal,201.0,0.0,15.0,0.5,,,SERIAL123\r\n"
)

DAILY_INSULIN_CSV = (
    "﻿Name:Test Patient,Date Range:2026-01-01 - 2026-01-02\r\n"
    "Timestamp,Total Bolus (U),Total Insulin (U),Total Basal (U),Serial Number\r\n"
    "2026-01-01 23:59,2.5,10.5,8.0,SERIAL123\r\n"
    "2026-01-02 23:59,3.0,9.0,6.0,SERIAL123\r\n"
)


def _write_export_dir(root: Path) -> None:
    (root / "Insulin data").mkdir(parents=True, exist_ok=True)
    (root / "cgm_data_1.csv").write_text(CGM_CSV, encoding="utf-8")
    (root / "bg_data_1.csv").write_text(BG_CSV, encoding="utf-8")
    (root / "Insulin data" / "bolus_data_1.csv").write_text(BOLUS_CSV, encoding="utf-8")
    (root / "Insulin data" / "insulin_data_1.csv").write_text(DAILY_INSULIN_CSV, encoding="utf-8")


class TestGlookoExportLoader(unittest.TestCase):
    """Parsing of a real multi-file Glooko export (directory or zip)."""

    def test_loads_from_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_export_dir(root)

            data = GlookoDataLoader.load_glooko_export(root)

            self.assertEqual(len(data.glucose_readings), 3)  # 2 cgm + 1 bg
            self.assertEqual(sum(1 for r in data.glucose_readings if r.source == "cgm"), 2)
            self.assertEqual(sum(1 for r in data.glucose_readings if r.source == "meter"), 1)

    def test_loads_from_zip_via_auto_detect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            _write_export_dir(root)

            zip_path = Path(tmp) / "export.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                for f in root.rglob("*.csv"):
                    zf.write(f, f.relative_to(root))

            data = GlookoDataLoader.load(zip_path)

            self.assertEqual(len(data.glucose_readings), 3)

    def test_bolus_file_splits_into_meal_and_bolus_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_export_dir(root)

            data = GlookoDataLoader.load_glooko_export(root)

            self.assertEqual(len(data.meals), 1)
            self.assertEqual(data.meals[0].carbs, 30.0)

            bolus_events = [e for e in data.insulin_events if e.event_type == "bolus"]
            self.assertEqual(len(bolus_events), 2)
            self.assertAlmostEqual(sum(e.amount for e in bolus_events), 2.5)

    def test_daily_insulin_file_becomes_synthetic_basal_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_export_dir(root)

            data = GlookoDataLoader.load_glooko_export(root)

            basal_events = [e for e in data.insulin_events if e.event_type == "basal"]
            self.assertEqual(len(basal_events), 2)
            self.assertEqual({e.amount for e in basal_events}, {8.0, 6.0})

    def test_missing_path_raises(self):
        with self.assertRaises(ValueError):
            GlookoDataLoader.load_glooko_export("/nonexistent/path/that/is/not/a/file.txt")


if __name__ == "__main__":
    unittest.main()
