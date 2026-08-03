"""Tests for the schedule-discovery algorithm: the generic boundary-merge
algorithm in src/schedule_discovery.py, and the engine's use of it to
propose a new (<=8 segment) time schedule for ICR, ISF, and Target BG.
"""

import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import GlucoseReading, MealEvent, InsulinEvent, GlucoseUnit, GloocolData
from src.schedule_discovery import discover_schedule
from src.recommendation_engine import OmnipodRecommendationEngine


def _gr(ts: datetime, value: float) -> GlucoseReading:
    return GlucoseReading(timestamp=ts, value=max(45.0, min(395.0, value)), unit=GlucoseUnit.MG_DL)


class TestDiscoverSchedule(unittest.TestCase):
    def test_merges_adjacent_hours_with_same_lean(self):
        lean = {h: ("raise" if 8 <= h < 12 else "lower" if 20 <= h < 23 else "neutral") for h in range(24)}
        n = {h: 5 for h in range(24)}

        segments = discover_schedule(lean, n, max_segments=8, min_segment_hours=2)

        # every returned segment is internally consistent (same lean throughout,
        # verified indirectly): boundaries should land at the lean transitions
        starts = [s for s, _ in segments]
        self.assertIn(8, starts)
        self.assertLessEqual(len(segments), 8)
        total_hours = sum(e - s for s, e in segments)
        self.assertEqual(total_hours, 24)

    def test_all_neutral_collapses_to_one_segment(self):
        segments = discover_schedule({}, {}, max_segments=8, min_segment_hours=2)
        self.assertEqual(segments, [(0, 24)])

    def test_respects_min_segment_hours(self):
        lean = {h: ("raise" if h == 12 else "neutral") for h in range(24)}
        n = {h: 1 for h in range(24)}

        segments = discover_schedule(lean, n, max_segments=8, min_segment_hours=2)

        for start, end in segments:
            self.assertGreaterEqual(end - start, 2)

    def test_max_segments_cap_is_never_exceeded(self):
        # Worst case: lean flips every single hour.
        lean = {h: ("raise" if h % 2 == 0 else "lower") for h in range(24)}
        n = {h: 1 for h in range(24)}

        segments = discover_schedule(lean, n, max_segments=8, min_segment_hours=2)

        self.assertLessEqual(len(segments), 8)
        total_hours = sum(e - s for s, e in segments)
        self.assertEqual(total_hours, 24)

    def test_cap_merges_weakest_evidence_boundary_first(self):
        # Two adjacent one-hour blocks with very little evidence should be
        # the first to merge away when the cap forces a reduction, leaving
        # well-evidenced blocks intact.
        lean = {0: "raise", 1: "lower", 2: "raise", 3: "lower"}
        n = {0: 1, 1: 1, 2: 50, 3: 50}
        # 4 blocks (0,1)(1,2)(2,3)(3,4) each width 1 -- min_segment_hours=1
        # keeps them from auto-merging on width, forcing the cap logic to choose.
        segments = discover_schedule(lean, n, max_segments=3, min_segment_hours=1)

        self.assertLessEqual(len(segments), 3)
        # the low-evidence pair (hours 0-1) should have merged into each other
        self.assertIn((0, 2), segments)


class TestTargetHourLean(unittest.TestCase):
    def test_magnitude_buckets(self):
        decide = OmnipodRecommendationEngine._target_hour_lean
        self.assertEqual(decide(below_pct=0, above_pct=50), "net_very_high")
        self.assertEqual(decide(below_pct=0, above_pct=20), "net_high")
        self.assertEqual(decide(below_pct=10, above_pct=10), "net_neutral")
        self.assertEqual(decide(below_pct=20, above_pct=0), "net_low")
        self.assertEqual(decide(below_pct=50, above_pct=0), "net_very_low")

    def test_uniformly_high_patient_still_shows_a_magnitude_gradient(self):
        """A patient who runs high nearly every hour (net always positive)
        must not collapse every hour into the same bucket -- that was the
        original bug: a plain above>below binary comparison has no power to
        distinguish a mild elevation from a severe one."""
        decide = OmnipodRecommendationEngine._target_hour_lean
        mild = decide(below_pct=2, above_pct=15)     # net ~13
        severe = decide(below_pct=0, above_pct=68)   # net 68
        self.assertNotEqual(mild, severe)


def _build_target_pattern_data(days: int = 6) -> GloocolData:
    """Glucose runs strongly high 08:00-11:00, mildly high 00:00-08:00, and
    in-range the rest of the day, repeated across `days` days -- a rough
    stand-in for the real dawn-spike pattern found in the session's
    analysis of actual CGM data.
    """
    data = GloocolData()
    base = datetime(2026, 1, 1)
    for day in range(days):
        day_start = base + timedelta(days=day)
        for step, minute in enumerate(range(0, 24 * 60, 15)):
            hour = minute / 60.0
            ts = day_start + timedelta(minutes=minute)
            if 8 <= hour < 11:
                # ~90% of readings above range -- a severe, sustained spike.
                value = 130.0 if step % 10 == 0 else 250.0
            elif hour < 8:
                # ~25% of readings above range -- a milder elevation. TIR is
                # a *fraction-above-threshold* signal, not a raw-magnitude
                # one, so it needs within-hour variability to show a
                # gradient at all -- a constant value that's always above
                # (or always below) the boundary reads identically to any
                # other constant value on the same side of it.
                value = 220.0 if step % 4 == 0 else 150.0
            else:
                value = 130.0
            data.glucose_readings.append(_gr(ts, value))
    return data


class TestScheduleProposalEngine(unittest.TestCase):
    def test_empty_without_current_settings(self):
        data = _build_target_pattern_data()
        engine = OmnipodRecommendationEngine(data)
        engine.generate_recommendations()

        self.assertEqual(engine.generate_schedule_proposal(), {})

    def test_target_schedule_finds_distinct_blocks_and_respects_cap(self):
        data = _build_target_pattern_data(days=6)
        # Two current segments with different baselines (a single flat
        # segment would give every discovered block the same starting
        # baseline and the same fixed step, masking whether boundary
        # discovery actually found distinct blocks -- real pump configs
        # are segmented like this too).
        current_settings = {
            "active_insulin_time": 4.0,
            "target_segments": [
                {"start_hour": 0, "target": 140.0},
                {"start_hour": 8, "target": 120.0},
            ],
        }
        engine = OmnipodRecommendationEngine(data, current_settings=current_settings)
        engine.generate_recommendations()
        proposal = engine.generate_schedule_proposal()

        segments = proposal["target"]["segments"]
        self.assertGreater(len(segments), 1)
        self.assertLessEqual(len(segments), 8)

        # the 08:00-11:00 (severe) block should propose a lower target than
        # a milder overnight block
        severe = next(s for s in segments if s["start_hour"] <= 8 < s["end_hour"])
        mild = next(s for s in segments if s["start_hour"] <= 1 < s["end_hour"])
        self.assertLess(severe["proposed_value"], mild["proposed_value"])

    def test_isf_schedule_honestly_collapses_when_data_is_sparse(self):
        """Mirrors the real data's ISF sparsity: almost no correction-only
        events anywhere in the day. The algorithm must not invent an
        8-segment schedule from near-nothing."""
        data = GloocolData()
        base = datetime(2026, 1, 1)
        for day in range(10):
            for h in range(0, 24, 3):
                ts = base + timedelta(days=day, hours=h)
                data.glucose_readings.append(_gr(ts, 140.0))
        # a single correction-only event in the whole dataset
        data.insulin_events.append(InsulinEvent(timestamp=base + timedelta(hours=10), amount=1.0, event_type="bolus"))
        data.glucose_readings.append(_gr(base + timedelta(hours=9, minutes=45), 220.0))
        data.glucose_readings.append(_gr(base + timedelta(hours=13, minutes=30), 210.0))

        current_settings = {
            "active_insulin_time": 4.0,
            "isf_segments": [{"start_hour": 0, "value": 100.0}],
        }
        engine = OmnipodRecommendationEngine(data, current_settings=current_settings)
        engine.generate_recommendations()
        proposal = engine.generate_schedule_proposal()

        self.assertEqual(len(proposal["isf"]["segments"]), 1)
        self.assertIsNotNone(proposal["isf"]["note"])


if __name__ == "__main__":
    unittest.main()
