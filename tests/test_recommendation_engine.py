"""Tests for the safety-critical logic in OmnipodRecommendationEngine."""

import sys
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    GlucoseReading, MealEvent, InsulinEvent, GlucoseUnit,
    GloocolData,
)
from src.analysis import GlucoseAnalyzer
from src.recommendation_engine import OmnipodRecommendationEngine


def _make_multi_day_data(days: int = 10, daily_bolus_units: float = 8.0, daily_basal_units: float = 12.0) -> GloocolData:
    """Synthetic data: regular CGM readings every 15 min, three meals/boluses a
    day, and basal events, spread across `days` days."""
    data = GloocolData()
    start = datetime(2026, 1, 1, 0, 0, 0)

    for day in range(days):
        day_start = start + timedelta(days=day)

        for minute in range(0, 24 * 60, 15):
            ts = day_start + timedelta(minutes=minute)
            # gentle oscillation between ~90 and ~150 mg/dL
            value = 120 + 30 * ((minute % 240) - 120) / 120
            data.glucose_readings.append(
                GlucoseReading(timestamp=ts, value=value, unit=GlucoseUnit.MG_DL)
            )

        for meal_hour, carbs in [(8, 45.0), (13, 60.0), (19, 50.0)]:
            meal_time = day_start + timedelta(hours=meal_hour)
            data.meals.append(MealEvent(timestamp=meal_time, carbs=carbs))
            data.insulin_events.append(
                InsulinEvent(
                    timestamp=meal_time + timedelta(minutes=5),
                    amount=daily_bolus_units / 3,
                    event_type="bolus",
                )
            )

        # basal delivered as small discrete events through the day
        for hour in range(0, 24, 4):
            data.insulin_events.append(
                InsulinEvent(
                    timestamp=day_start + timedelta(hours=hour),
                    amount=daily_basal_units / 6,
                    event_type="basal",
                )
            )

    return data


class TestCorrectionTarget(unittest.TestCase):
    """correction_target must never fall to/below the hypoglycemia threshold."""

    def test_correction_target_never_below_target_min(self):
        data = _make_multi_day_data()
        # Overwrite readings with a low-running population (mean well under 70).
        data.glucose_readings = [
            GlucoseReading(
                timestamp=datetime(2026, 1, 1) + timedelta(minutes=5 * i),
                value=60.0,
                unit=GlucoseUnit.MG_DL,
            )
            for i in range(500)
        ]

        engine = OmnipodRecommendationEngine(data)
        settings = engine.generate_recommendations()

        self.assertGreaterEqual(settings.correction_target, settings.target_glucose_min + 10)
        self.assertLessEqual(settings.correction_target, settings.target_glucose_max)

    def test_correction_target_is_rounded_to_the_nearest_integer(self):
        """A fractional BG target isn't meaningful -- a pump can't be set to
        '105.7 mg/dL'. mean=115.7 would give a candidate of 105.7 before
        rounding (mean - 10, since mean < 120)."""
        data = GloocolData()
        base = datetime(2026, 1, 1)
        data.glucose_readings = [
            GlucoseReading(timestamp=base + timedelta(minutes=5 * i), value=115.7, unit=GlucoseUnit.MG_DL)
            for i in range(500)
        ]

        engine = OmnipodRecommendationEngine(data)
        settings = engine.generate_recommendations()

        self.assertEqual(settings.correction_target, round(settings.correction_target))
        self.assertEqual(settings.correction_target, 106)


class TestMaxBasalAndBolusScaleWithDose(unittest.TestCase):
    """max_basal/max_bolus must scale with the patient's actual dosing, not
    sit at a fixed floor regardless of how little insulin they use."""

    def test_low_dose_patient_gets_low_ceilings(self):
        data = _make_multi_day_data(days=10, daily_bolus_units=3.0, daily_basal_units=5.0)
        engine = OmnipodRecommendationEngine(data)
        settings = engine.generate_recommendations()

        # Old behavior hardcoded max_basal floor of 3.0u/hr and flat max_bolus
        # of 30u regardless of dose. A ~8u/day TDD patient should get much
        # lower ceilings than that.
        self.assertLess(settings.max_basal, 3.0)
        self.assertLess(settings.max_bolus, 30.0)
        self.assertGreater(settings.max_basal, 0)
        self.assertGreater(settings.max_bolus, 0)

    def test_higher_dose_patient_gets_higher_ceilings_than_low_dose_patient(self):
        low = OmnipodRecommendationEngine(
            _make_multi_day_data(days=10, daily_bolus_units=3.0, daily_basal_units=5.0)
        ).generate_recommendations()
        high = OmnipodRecommendationEngine(
            _make_multi_day_data(days=10, daily_bolus_units=20.0, daily_basal_units=30.0)
        ).generate_recommendations()

        self.assertGreater(high.max_bolus, low.max_bolus)
        self.assertGreater(high.max_basal, low.max_basal)


class TestTddBasedRatios(unittest.TestCase):
    """ISF/carb ratio should use the TDD-based rule when dosing history exists,
    and fall back safely (with a warning) when it doesn't."""

    def test_uses_tdd_rule_when_insulin_history_present(self):
        data = _make_multi_day_data(days=10, daily_bolus_units=10.0, daily_basal_units=10.0)
        engine = OmnipodRecommendationEngine(data)
        tdd = engine.analyzer.get_total_daily_dose()
        settings = engine.generate_recommendations()

        self.assertIsNotNone(tdd)
        expected_isf_afternoon = round(engine.ISF_RULE_CONSTANT / tdd, 1)
        expected_carb_ratio_afternoon = round(
            OmnipodRecommendationEngine._clamp_carb_ratio(engine.CARB_RATIO_RULE_CONSTANT / tdd), 1
        )
        # Afternoon hours have no time-of-day multiplier applied to ISF and a
        # 1.0x multiplier for carb ratio, so they should match the rule
        # constants directly (mod the bounded meal-response modifier).
        self.assertAlmostEqual(settings.insulin_sensitivity_factor.factors[14], expected_isf_afternoon, delta=expected_isf_afternoon * 0.01 + 0.5)
        self.assertAlmostEqual(settings.carb_ratio.ratios[14], expected_carb_ratio_afternoon, delta=expected_carb_ratio_afternoon * 0.25)

    def test_falls_back_with_warning_when_no_insulin_history(self):
        data = _make_multi_day_data(days=10)
        data.insulin_events = []  # strip all dosing history

        engine = OmnipodRecommendationEngine(data)
        settings = engine.generate_recommendations()

        self.assertTrue(any("no insulin dosing history" in w.lower() for w in settings.warnings))


class TestOutlierFiltering(unittest.TestCase):
    """CGM sensor-error spikes/dropouts should not skew statistics."""

    def test_outlier_readings_excluded_from_statistics(self):
        data = GloocolData()
        base = datetime(2026, 1, 1)
        for i in range(20):
            data.glucose_readings.append(
                GlucoseReading(timestamp=base + timedelta(minutes=5 * i), value=120.0, unit=GlucoseUnit.MG_DL)
            )
        # Sensor error spikes well outside physiological range.
        data.glucose_readings.append(
            GlucoseReading(timestamp=base + timedelta(minutes=200), value=900.0, unit=GlucoseUnit.MG_DL)
        )
        data.glucose_readings.append(
            GlucoseReading(timestamp=base + timedelta(minutes=205), value=5.0, unit=GlucoseUnit.MG_DL)
        )

        analyzer = GlucoseAnalyzer(data)
        stats = analyzer.get_statistics()

        self.assertEqual(analyzer.excluded_reading_count, 2)
        self.assertAlmostEqual(stats["mean"], 120.0, places=3)
        self.assertEqual(stats["max"], 120.0)


class TestBasalRequirementsPerformance(unittest.TestCase):
    """get_basal_requirements_by_hour must not be O(n^2) on realistic exports."""

    def test_completes_quickly_on_large_dataset(self):
        data = GloocolData()
        base = datetime(2026, 1, 1)
        # ~90 days at 5-minute intervals, ~25,920 readings.
        for i in range(90 * 24 * 12):
            data.glucose_readings.append(
                GlucoseReading(
                    timestamp=base + timedelta(minutes=5 * i),
                    value=100 + (i % 40),
                    unit=GlucoseUnit.MG_DL,
                )
            )

        analyzer = GlucoseAnalyzer(data)
        start = time.monotonic()
        result = analyzer.get_basal_requirements_by_hour()
        elapsed = time.monotonic() - start

        self.assertEqual(len(result), 24)
        self.assertLess(elapsed, 5.0, f"basal requirement calculation took {elapsed:.2f}s, expected O(n)")


class TestDataSufficiencyWarning(unittest.TestCase):
    """Sparse data should be flagged as low-confidence, not presented as-is."""

    def test_sparse_data_produces_warning(self):
        data = GloocolData()
        base = datetime(2026, 1, 1)
        for i in range(10):
            data.glucose_readings.append(
                GlucoseReading(timestamp=base + timedelta(minutes=5 * i), value=110.0, unit=GlucoseUnit.MG_DL)
            )

        engine = OmnipodRecommendationEngine(data)
        settings = engine.generate_recommendations()

        self.assertTrue(any("day(s) of glucose data" in w for w in settings.warnings))


class TestSummaryReportDataSummary(unittest.TestCase):
    """generate_summary_report()'s data_summary should surface who the
    report is about and how much data was actually considered."""

    def test_includes_patient_name_and_duration(self):
        data = _make_multi_day_data(days=10)
        data.patient_name = "Test Patient"

        engine = OmnipodRecommendationEngine(data)
        summary = engine.generate_summary_report()["data_summary"]

        self.assertEqual(summary["patient_name"], "Test Patient")
        self.assertEqual(summary["duration_days"], 10)

    def test_patient_name_and_duration_are_none_without_data(self):
        engine = OmnipodRecommendationEngine(GloocolData())
        summary = engine.generate_summary_report()["data_summary"]

        self.assertIsNone(summary["patient_name"])
        self.assertIsNone(summary["duration_days"])


if __name__ == "__main__":
    unittest.main()
