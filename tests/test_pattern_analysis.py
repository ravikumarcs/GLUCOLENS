"""Tests for the baseline-relative, evidence-gated pattern analysis
(clean-window drift, meal-response, correction-only-event, TIR-by-segment)
and the engine's baseline-relative recommendation path built on top of it.
"""

import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import GlucoseReading, MealEvent, InsulinEvent, GlucoseUnit, GloocolData
from src.analysis import GlucoseAnalyzer
from src.recommendation_engine import OmnipodRecommendationEngine


def _gr(ts: datetime, value: float) -> GlucoseReading:
    return GlucoseReading(timestamp=ts, value=max(45.0, min(395.0, value)), unit=GlucoseUnit.MG_DL)


def _build_drift_data(direction: str, days: int = 5, hour_range=(0, 6)) -> GloocolData:
    """Glucose steadily rises/falls during hour_range each day, flat
    elsewhere. No meals/boluses at all, so the entire span is one clean
    window and each day contributes one drift instance per segment.

    Baseline (200) and slope magnitude (25 mg/dL/hr) are chosen so a 6-hour
    window stays well clear of the physiological clamp floor/ceiling
    (45-395) applied in _gr -- clamping would flatten part of the ramp and
    understate the fitted slope.
    """
    data = GloocolData()
    base = datetime(2026, 1, 1)
    start_h, end_h = hour_range
    slope = {"rising": 25.0, "falling": -25.0, "stable": 0.0}[direction]

    for day in range(days):
        day_start = base + timedelta(days=day)
        for minute in range(0, 24 * 60, 15):
            hour = minute / 60.0
            ts = day_start + timedelta(minutes=minute)
            if start_h <= hour < end_h:
                value = 200 + slope * (hour - start_h)
            else:
                value = 150.0
            data.glucose_readings.append(_gr(ts, value))

    return data


def _build_meal_response_data() -> GloocolData:
    data = GloocolData()
    base = datetime(2026, 1, 1)

    # Meal 1: in-range pre-meal, sustained spike -> too_weak
    meal1 = base + timedelta(hours=8)
    data.meals.append(MealEvent(timestamp=meal1, carbs=40))
    for m in range(-30, 0, 5):
        data.glucose_readings.append(_gr(meal1 + timedelta(minutes=m), 110))
    for m in range(120, 240, 15):
        data.glucose_readings.append(_gr(meal1 + timedelta(minutes=m), 260))

    # Meal 2: in-range pre-meal, low in post window -> too_strong
    meal2 = base + timedelta(hours=13)
    data.meals.append(MealEvent(timestamp=meal2, carbs=40))
    for m in range(-30, 0, 5):
        data.glucose_readings.append(_gr(meal2 + timedelta(minutes=m), 100))
    for m in range(120, 240, 15):
        data.glucose_readings.append(_gr(meal2 + timedelta(minutes=m), 65))

    # Meal 3: in-range pre-meal, moderate response -> ok
    meal3 = base + timedelta(hours=18)
    data.meals.append(MealEvent(timestamp=meal3, carbs=40))
    for m in range(-30, 0, 5):
        data.glucose_readings.append(_gr(meal3 + timedelta(minutes=m), 110))
    for m in range(120, 240, 15):
        data.glucose_readings.append(_gr(meal3 + timedelta(minutes=m), 150))

    # Meal 4: out-of-range pre-meal -> excluded entirely
    meal4 = base + timedelta(days=1, hours=8)
    data.meals.append(MealEvent(timestamp=meal4, carbs=40))
    for m in range(-30, 0, 5):
        data.glucose_readings.append(_gr(meal4 + timedelta(minutes=m), 250))
    for m in range(120, 240, 15):
        data.glucose_readings.append(_gr(meal4 + timedelta(minutes=m), 260))

    return data


def _build_correction_event_data() -> GloocolData:
    data = GloocolData()
    base = datetime(2026, 1, 1)

    # Event A: correction-only, still elevated 3-4h later -> too_weak
    t1 = base + timedelta(hours=10)
    data.insulin_events.append(InsulinEvent(timestamp=t1, amount=2.0, event_type="bolus"))
    data.glucose_readings.append(_gr(t1 - timedelta(minutes=5), 220))
    for m in range(180, 240, 15):
        data.glucose_readings.append(_gr(t1 + timedelta(minutes=m), 210))

    # Event B: correction-only, goes low -> too_strong
    t2 = base + timedelta(hours=15)
    data.insulin_events.append(InsulinEvent(timestamp=t2, amount=1.5, event_type="bolus"))
    data.glucose_readings.append(_gr(t2 - timedelta(minutes=5), 200))
    for m in range(180, 240, 15):
        data.glucose_readings.append(_gr(t2 + timedelta(minutes=m), 60))

    # Event C: within 3h of a meal -> excluded (food response, not isolation)
    meal = base + timedelta(hours=20)
    data.meals.append(MealEvent(timestamp=meal, carbs=30))
    t3 = meal + timedelta(hours=1)
    data.insulin_events.append(InsulinEvent(timestamp=t3, amount=1.0, event_type="bolus"))
    data.glucose_readings.append(_gr(t3 - timedelta(minutes=5), 200))
    for m in range(180, 240, 15):
        data.glucose_readings.append(_gr(t3 + timedelta(minutes=m), 210))

    return data


class TestFindCleanWindows(unittest.TestCase):
    def test_finds_overnight_stretch_and_excludes_meal_windows(self):
        data = GloocolData()
        base = datetime(2026, 1, 1)
        for minute in range(0, 24 * 60, 5):
            data.glucose_readings.append(_gr(base + timedelta(minutes=minute), 130))
        for hour in (8, 13, 19):
            data.meals.append(MealEvent(timestamp=base + timedelta(hours=hour), carbs=30))

        analyzer = GlucoseAnalyzer(data)
        windows = analyzer.find_clean_windows(min_hours=5.0, active_insulin_time=4.0)

        self.assertTrue(any(w["duration_hours"] >= 8 for w in windows))
        for meal_hour in (8, 13, 19):
            # A point well inside the 4h post-meal exclusion window (not the
            # meal timestamp itself, which is the exact, ambiguous boundary
            # between the preceding clean interval and the exclusion).
            mid_exclusion = base + timedelta(hours=meal_hour + 2)
            self.assertFalse(any(w["start"] <= mid_exclusion <= w["end"] for w in windows))


class TestComputeBasalDrift(unittest.TestCase):
    def test_detects_rising_drift_with_sufficient_evidence(self):
        data = _build_drift_data("rising", days=5, hour_range=(0, 6))
        analyzer = GlucoseAnalyzer(data)
        result = analyzer.compute_basal_drift((0, 6))

        self.assertEqual(result["direction"], "rising")
        self.assertTrue(result["sufficient_evidence"])
        self.assertGreaterEqual(result["n_rising"], 3)
        self.assertGreater(result["median_slope"], 0)

    def test_detects_falling_drift_with_sufficient_evidence(self):
        data = _build_drift_data("falling", days=5, hour_range=(0, 6))
        analyzer = GlucoseAnalyzer(data)
        result = analyzer.compute_basal_drift((0, 6))

        self.assertEqual(result["direction"], "falling")
        self.assertTrue(result["sufficient_evidence"])
        self.assertLess(result["median_slope"], 0)

    def test_flat_segment_has_no_direction_with_sufficient_evidence(self):
        data = _build_drift_data("rising", days=5, hour_range=(0, 6))
        analyzer = GlucoseAnalyzer(data)
        result = analyzer.compute_basal_drift((12, 18))  # flat in this dataset

        self.assertFalse(result["sufficient_evidence"])

    def test_too_few_days_is_insufficient_evidence(self):
        data = _build_drift_data("rising", days=2, hour_range=(0, 6))
        analyzer = GlucoseAnalyzer(data)
        result = analyzer.compute_basal_drift((0, 6))

        self.assertFalse(result["sufficient_evidence"])


class TestAnalyzeMealResponseForIcr(unittest.TestCase):
    def setUp(self):
        analyzer = GlucoseAnalyzer(_build_meal_response_data())
        self.results = analyzer.analyze_meal_response_for_icr()

    def test_out_of_range_pre_meal_excluded(self):
        self.assertEqual(len(self.results), 3)

    def test_classifications(self):
        by_hour = {r["meal_time"].hour: r["classification"] for r in self.results}
        self.assertEqual(by_hour[8], "too_weak")
        self.assertEqual(by_hour[13], "too_strong")
        self.assertEqual(by_hour[18], "ok")

    def test_low_outside_2_to_3h_crash_window_is_not_too_strong(self):
        """A low at 3.5h (outside the guide's 2-3h crash window, inside the
        3h too-weak check's tolerance) should not be classified too_strong --
        it also shouldn't be too_weak, since it did come down by the 3h
        check. This is the guide's narrower crash window in action: a wider
        2-4h window (the previous implementation) would have caught this low
        and called it too_strong."""
        data = GloocolData()
        base = datetime(2026, 1, 1)
        meal = base + timedelta(hours=8)
        data.meals.append(MealEvent(timestamp=meal, carbs=40))
        for m in range(-30, 0, 5):
            data.glucose_readings.append(_gr(meal + timedelta(minutes=m), 110))
        for m in (120, 140, 160):  # 2h-2h40 -- normal, outside crash window issue
            data.glucose_readings.append(_gr(meal + timedelta(minutes=m), 150))
        data.glucose_readings.append(_gr(meal + timedelta(minutes=210), 60))  # 3.5h low

        analyzer = GlucoseAnalyzer(data)
        results = analyzer.analyze_meal_response_for_icr()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["classification"], "ok")


class TestAnalyzeCorrectionOnlyEvents(unittest.TestCase):
    def setUp(self):
        analyzer = GlucoseAnalyzer(_build_correction_event_data())
        self.results = analyzer.analyze_correction_only_events()

    def test_near_meal_event_excluded(self):
        self.assertEqual(len(self.results), 2)

    def test_classifications(self):
        by_hour = {r["time"].hour: r["classification"] for r in self.results}
        self.assertEqual(by_hour[10], "too_weak")
        self.assertEqual(by_hour[15], "too_strong")


class TestBaselineRelativeEngine(unittest.TestCase):
    def test_basal_segment_adjusted_when_drift_found(self):
        data = _build_drift_data("rising", days=5, hour_range=(0, 6))
        current_settings = {
            "active_insulin_time": 4.0,
            "basal_segments": [{"start_hour": 0, "rate": 0.4}, {"start_hour": 6, "rate": 0.4}],
        }

        engine = OmnipodRecommendationEngine(data, current_settings=current_settings)
        settings = engine.generate_recommendations()
        findings = engine.generate_findings_report()

        basal_findings = [f for f in findings if f["setting"] == "Basal"]
        seg0 = next(f for f in basal_findings if f["time_block"] == "00:00-06:00")
        seg1 = next(f for f in basal_findings if f["time_block"] == "06:00-24:00")

        self.assertEqual(seg0["proposed_direction"], "raise")
        self.assertAlmostEqual(seg0["proposed_value"], round(0.4 * 1.15, 2))
        self.assertIn("supported", seg0["confidence"])
        self.assertEqual(seg1["proposed_direction"], "no change")

        self.assertAlmostEqual(settings.basal_profile.rates[0], seg0["proposed_value"])
        self.assertAlmostEqual(settings.basal_profile.rates[10], 0.4)

        self.assertTrue(any("address basal" in w.lower() for w in settings.warnings))

        # Concrete evidence: one row per agreeing clean window, with a date,
        # a BG value at each end of the window, and a slope.
        self.assertEqual(len(seg0["evidence"]), 5)
        row = seg0["evidence"][0]
        for key in ("date", "time_start", "bg_start", "time_end", "bg_end", "slope_mgdl_per_hr"):
            self.assertIn(key, row)
        self.assertGreater(row["slope_mgdl_per_hr"], 0)

    def test_insufficient_evidence_leaves_segment_unchanged(self):
        data = _build_drift_data("rising", days=2, hour_range=(0, 6))
        current_settings = {
            "active_insulin_time": 4.0,
            "basal_segments": [{"start_hour": 0, "rate": 0.4}],
        }

        engine = OmnipodRecommendationEngine(data, current_settings=current_settings)
        engine.generate_recommendations()
        findings = engine.generate_findings_report()

        basal_finding = next(f for f in findings if f["setting"] == "Basal")
        self.assertEqual(basal_finding["proposed_direction"], "no change")
        self.assertEqual(basal_finding["proposed_value"], 0.4)
        self.assertEqual(basal_finding["confidence"], "insufficient evidence")

    def test_findings_report_empty_without_current_settings(self):
        data = _build_drift_data("rising", days=5, hour_range=(0, 6))
        engine = OmnipodRecommendationEngine(data)
        engine.generate_recommendations()

        self.assertEqual(engine.generate_findings_report(), [])

    def test_findings_report_ordered_basal_icr_cf_target(self):
        data = _build_meal_response_data()
        current_settings = {
            "active_insulin_time": 4.0,
            "basal_segments": [{"start_hour": 0, "rate": 0.4}],
            "carb_ratio_segments": [{"start_hour": 0, "value": 15.0}],
            "isf_segments": [{"start_hour": 0, "value": 100.0}],
            "target_segments": [{"start_hour": 0, "target": 120.0}],
        }

        engine = OmnipodRecommendationEngine(data, current_settings=current_settings)
        engine.generate_recommendations()
        findings = engine.generate_findings_report()

        settings_seen = [f["setting"] for f in findings]
        expected_order = [
            "Basal",
            "Insulin-to-Carb Ratio (ICR)",
            "Correction Factor / Sensitivity (ISF)",
            "Target Glucose (BGT)",
        ]
        # every setting present should appear in this relative order
        indices = [expected_order.index(s) for s in settings_seen]
        self.assertEqual(indices, sorted(indices))

        # Every finding carries an "evidence" list, even when there wasn't
        # enough of it to propose a change -- it should still show what was
        # evaluated (dates, BG values), not just the aggregate count.
        icr_finding = next(f for f in findings if f["setting"] == "Insulin-to-Carb Ratio (ICR)")
        self.assertIn("evidence", icr_finding)
        self.assertTrue(icr_finding["evidence"])
        icr_row = icr_finding["evidence"][0]
        for key in ("date", "time", "carbs", "bg_before", "bg_after"):
            self.assertIn(key, icr_row)

        target_finding = next(f for f in findings if f["setting"] == "Target Glucose (BGT)")
        self.assertIn("evidence", target_finding)

    def test_target_finding_proposed_value_is_rounded_to_the_nearest_integer(self):
        """A fractional BG target isn't meaningful -- a pump can't be set to
        '123.3 mg/dL'. current=133.3 with a highs-dominant pattern proposes
        133.3 - 10 = 123.3 before rounding.
        """
        data = GloocolData()
        base = datetime(2026, 1, 1)
        for day in range(5):
            day_start = base + timedelta(days=day)
            for minute in range(0, 24 * 60, 15):
                data.glucose_readings.append(_gr(day_start + timedelta(minutes=minute), 220.0))

        current_settings = {
            "active_insulin_time": 4.0,
            "target_segments": [{"start_hour": 0, "target": 133.3}],
        }
        engine = OmnipodRecommendationEngine(data, current_settings=current_settings)
        engine.generate_recommendations()
        finding = next(
            f for f in engine.generate_findings_report() if f["setting"] == "Target Glucose (BGT)"
        )

        self.assertEqual(finding["proposed_direction"], "lower")
        self.assertEqual(finding["proposed_value"], 123)
        self.assertIsInstance(finding["proposed_value"], int)

    def test_icr_evidence_reflects_the_meals_driving_the_proposal(self):
        """With enough qualifying meals to trigger a proposal, the evidence
        rows should be exactly the too_weak meals that drove it -- concrete,
        dated, with real BG values -- not the full evaluated set."""
        data = GloocolData()
        base = datetime(2026, 1, 1)
        for day in range(4):
            meal = base + timedelta(days=day, hours=8)
            data.meals.append(MealEvent(timestamp=meal, carbs=40))
            for m in range(-30, 0, 5):
                data.glucose_readings.append(_gr(meal + timedelta(minutes=m), 110))
            for m in range(150, 210, 10):
                data.glucose_readings.append(_gr(meal + timedelta(minutes=m), 260))

        current_settings = {
            "active_insulin_time": 4.0,
            "carb_ratio_segments": [{"start_hour": 0, "value": 20.0}],
        }
        engine = OmnipodRecommendationEngine(data, current_settings=current_settings)
        engine.generate_recommendations()
        finding = engine.generate_findings_report()[0]

        self.assertEqual(finding["proposed_direction"], "lower")
        self.assertEqual(len(finding["evidence"]), 4)
        for row in finding["evidence"]:
            self.assertEqual(row["bg_before"], 110.0)
            self.assertEqual(row["bg_after"], 260.0)
            self.assertEqual(row["carbs"], 40)


if __name__ == "__main__":
    unittest.main()
