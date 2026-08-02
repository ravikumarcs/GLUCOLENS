"""Analysis of glucose data to identify patterns and metrics."""

import bisect
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np

from .models import GlucoseReading, MealEvent, GloocolData
from .segments import hours_in_range


class GlucoseAnalyzer:
    """Analyze glucose patterns and metrics."""

    # CGM readings outside this range are almost always sensor errors
    # (compression lows, warm-up spikes, calibration artifacts), not real
    # physiology, and should not feed into statistics or recommendations.
    MIN_VALID_GLUCOSE = 40.0
    MAX_VALID_GLUCOSE = 400.0

    # Absolute minimum history before generating hour-by-hour recommendations
    # at all; below this, output is still produced but flagged low-confidence.
    MIN_SUFFICIENT_DAYS = 3

    # Pattern-based (baseline-relative) analysis thresholds -- see the
    # clean-window/drift/meal-response/correction-event methods below.
    MIN_PATTERN_INSTANCES = 3  # "Rule of Three": don't act on a single outlier day
    BASAL_DRIFT_THRESHOLD_MGDL_PER_HR = 15.0  # noise floor below which drift isn't "steady"

    def __init__(self, data: GloocolData):
        """Initialize analyzer with Glooko data."""
        self.data = data

        all_readings = sorted(data.glucose_readings, key=lambda r: r.timestamp)
        self.readings: List[GlucoseReading] = [
            r for r in all_readings
            if self.MIN_VALID_GLUCOSE <= r.value <= self.MAX_VALID_GLUCOSE
        ]
        self.excluded_reading_count = len(all_readings) - len(self.readings)
        self._timestamps = [r.timestamp for r in self.readings]

    def _readings_in_range(self, start: datetime, end: datetime) -> List[GlucoseReading]:
        """Get valid (outlier-filtered) readings within a time range."""
        lo = bisect.bisect_left(self._timestamps, start)
        hi = bisect.bisect_right(self._timestamps, end)
        return self.readings[lo:hi]

    def get_statistics(self) -> Dict[str, float]:
        """Calculate glucose statistics."""
        if not self.readings:
            return {}

        values = [r.value for r in self.readings]

        return {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std_dev": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "q25": float(np.percentile(values, 25)),
            "q75": float(np.percentile(values, 75)),
        }

    def get_time_in_range(
        self,
        target_min: float = 70.0,
        target_max: float = 180.0
    ) -> Dict[str, float]:
        """Calculate percentage of time in range, above, and below."""
        if not self.readings:
            return {}

        total = len(self.readings)
        in_range = sum(1 for r in self.readings if target_min <= r.value <= target_max)
        below = sum(1 for r in self.readings if r.value < target_min)
        above = sum(1 for r in self.readings if r.value > target_max)

        return {
            "time_in_range_percent": (in_range / total) * 100 if total > 0 else 0,
            "time_below_percent": (below / total) * 100 if total > 0 else 0,
            "time_above_percent": (above / total) * 100 if total > 0 else 0,
        }

    def get_hourly_averages(self) -> Dict[int, float]:
        """Calculate average glucose for each hour of day."""
        hourly_values = {i: [] for i in range(24)}

        for reading in self.readings:
            hourly_values[reading.timestamp.hour].append(reading.value)

        return {hour: float(np.mean(values)) if values else 0
                for hour, values in hourly_values.items()}

    def get_glucose_variability(self) -> Dict[str, float]:
        """Calculate glucose variability metrics."""
        if len(self.readings) < 2:
            return {}

        # self.readings is already sorted by timestamp.
        changes = []
        for i in range(1, len(self.readings)):
            time_diff = (self.readings[i].timestamp - self.readings[i - 1].timestamp).total_seconds() / 60
            if time_diff > 0:
                rate = (self.readings[i].value - self.readings[i - 1].value) / time_diff
                changes.append(abs(rate))

        if not changes:
            return {}

        return {
            "avg_rate_of_change": float(np.mean(changes)),
            "max_rate_of_change": float(np.max(changes)),
            "std_dev_rate_of_change": float(np.std(changes)),
        }

    def detect_meal_response_pattern(self, window_hours: float = 3.0) -> List[Dict]:
        """Detect glucose response patterns after meals."""
        patterns = []

        for meal in self.data.meals:
            window_start = meal.timestamp - timedelta(minutes=30)
            window_end = meal.timestamp + timedelta(hours=window_hours)

            readings = self._readings_in_range(window_start, window_end)
            if not readings:
                continue

            pre_meal = [r.value for r in readings if r.timestamp < meal.timestamp]
            post_meal_readings = [r for r in readings if r.timestamp >= meal.timestamp]
            post_meal = [r.value for r in post_meal_readings]

            if pre_meal and post_meal:
                peak_reading = max(post_meal_readings, key=lambda r: r.value)
                pattern = {
                    "meal_time": meal.timestamp,
                    "carbs": meal.carbs,
                    "pre_meal_glucose": float(np.mean(pre_meal)),
                    "peak_glucose": float(np.max(post_meal)),
                    "peak_time_minutes": (peak_reading.timestamp - meal.timestamp).total_seconds() / 60,
                    "glucose_rise": float(np.max(post_meal) - np.mean(pre_meal)),
                }
                patterns.append(pattern)

        return patterns

    def detect_low_glucose_events(self, threshold: float = 70.0) -> List[Tuple[datetime, datetime]]:
        """Detect periods of low glucose."""
        events = []
        in_low = False
        low_start = None

        # self.readings is already sorted by timestamp.
        for reading in self.readings:
            if reading.value < threshold and not in_low:
                in_low = True
                low_start = reading.timestamp
            elif reading.value >= threshold and in_low:
                in_low = False
                events.append((low_start, reading.timestamp))

        return events

    def get_total_daily_dose(self) -> Optional[float]:
        """Average total daily insulin dose (units/day) from all recorded insulin events."""
        if not self.data.insulin_events:
            return None

        days = {event.timestamp.date() for event in self.data.insulin_events}
        if not days:
            return None

        total = sum(event.amount for event in self.data.insulin_events)
        return total / len(days)

    def get_basal_bolus_split(self) -> Optional[Dict[str, float]]:
        """Observed basal/bolus fraction of total insulin, if event types are tagged.

        Requires both basal and bolus events to be present before trusting the
        split — some exports never log continuous pump basal as discrete
        events, which would otherwise look like a (wrong) 0% basal fraction.
        """
        basal_total = sum(e.amount for e in self.data.insulin_events if e.event_type == "basal")
        bolus_total = sum(e.amount for e in self.data.insulin_events if e.event_type == "bolus")
        if basal_total <= 0 or bolus_total <= 0:
            return None

        total = basal_total + bolus_total
        return {
            "basal_fraction": basal_total / total,
            "bolus_fraction": bolus_total / total,
        }

    def assess_data_sufficiency(self) -> Dict:
        """Report how much usable data is available, to gate recommendation confidence."""
        if not self.readings:
            return {
                "days_covered": 0,
                "total_readings": 0,
                "excluded_readings": self.excluded_reading_count,
                "hours_with_data": 0,
                "is_sufficient": False,
            }

        start, end = self.readings[0].timestamp, self.readings[-1].timestamp
        days_covered = max(1, (end - start).days + 1)
        hours_present = {r.timestamp.hour for r in self.readings}

        return {
            "days_covered": days_covered,
            "total_readings": len(self.readings),
            "excluded_readings": self.excluded_reading_count,
            "hours_with_data": len(hours_present),
            "is_sufficient": days_covered >= self.MIN_SUFFICIENT_DAYS,
        }

    @staticmethod
    def _merge_windows(windows: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
        if not windows:
            return []
        windows = sorted(windows)
        merged = [list(windows[0])]
        for start, end in windows[1:]:
            if start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return [(s, e) for s, e in merged]

    def _build_exclusion_windows(self, active_insulin_time: float) -> Tuple[List[datetime], List[Tuple[datetime, datetime]]]:
        """Time windows to exclude from basal-need inference: active insulin from
        a meal bolus or manual bolus can mask or mimic a basal signal."""
        delta = timedelta(hours=active_insulin_time)
        raw_windows = [(meal.timestamp, meal.timestamp + delta) for meal in self.data.meals]
        raw_windows += [
            (event.timestamp, event.timestamp + delta)
            for event in self.data.insulin_events
            if event.event_type == "bolus"
        ]
        merged = self._merge_windows(raw_windows)
        starts = [w[0] for w in merged]
        return starts, merged

    @staticmethod
    def _in_exclusion_window(ts: datetime, starts: List[datetime], merged_windows: List[Tuple[datetime, datetime]]) -> bool:
        idx = bisect.bisect_right(starts, ts) - 1
        if idx >= 0:
            start, end = merged_windows[idx]
            if start <= ts <= end:
                return True
        return False

    def get_basal_requirements_by_hour(self, active_insulin_time: float = 4.0) -> Dict[int, Dict]:
        """Estimate basal insulin need per hour of day.

        Only uses "clean" CGM windows — periods with no meal or bolus in the
        preceding `active_insulin_time` hours — since glucose movement while
        insulin from a meal/correction is still active reflects that dose,
        not the basal rate. Returns, per hour, the estimated need and how
        many clean data points supported it (so low-confidence hours can be
        flagged rather than silently trusted).
        """
        starts, merged_windows = self._build_exclusion_windows(active_insulin_time)

        hourly_changes: Dict[int, List[float]] = {h: [] for h in range(24)}
        n = len(self.readings)
        window_seconds = 3600
        target_seconds = 1800

        for i in range(n - 1):
            reading = self.readings[i]
            if self._in_exclusion_window(reading.timestamp, starts, merged_windows):
                continue

            best = None
            best_diff = None
            j = i + 1
            while j < n:
                dt = (self.readings[j].timestamp - reading.timestamp).total_seconds()
                if dt >= window_seconds:
                    break
                diff = abs(dt - target_seconds)
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best = self.readings[j]
                j += 1

            if best is None or self._in_exclusion_window(best.timestamp, starts, merged_windows):
                continue

            minutes = (best.timestamp - reading.timestamp).total_seconds() / 60.0
            if minutes <= 0:
                continue

            rate = (best.value - reading.value) / minutes
            hourly_changes[reading.timestamp.hour].append(rate)

        result = {}
        for hour in range(24):
            changes = hourly_changes[hour]
            if changes:
                avg_change = float(np.mean(changes))
                # Rough estimate: 1 unit of basal offsets ~50 mg/dL rise per hour.
                result[hour] = {
                    "signal": max(0.05, abs(avg_change) / 50.0),
                    "clean_points": len(changes),
                }
            else:
                result[hour] = {"signal": None, "clean_points": 0}

        return result

    def find_clean_windows(self, min_hours: float = 5.0, active_insulin_time: float = 4.0) -> List[Dict]:
        """Contiguous stretches with no meal/bolus influence, at least
        `min_hours` long -- the complement of the meal/bolus exclusion
        windows, intersected with the CGM reading span. This is "overnight,
        or any 5+ hour fasting stretch" generically: no special-casing of
        clock time, any qualifying clean stretch counts.
        """
        if not self.readings:
            return []

        _, merged_exclusions = self._build_exclusion_windows(active_insulin_time)
        span_start, span_end = self.readings[0].timestamp, self.readings[-1].timestamp

        free_intervals = []
        cursor = span_start
        for ex_start, ex_end in merged_exclusions:
            if ex_start > cursor:
                free_intervals.append((cursor, min(ex_start, span_end)))
            cursor = max(cursor, ex_end)
            if cursor >= span_end:
                break
        if cursor < span_end:
            free_intervals.append((cursor, span_end))

        windows = []
        for start, end in free_intervals:
            duration_hours = (end - start).total_seconds() / 3600.0
            if duration_hours >= min_hours:
                windows.append({"start": start, "end": end, "duration_hours": duration_hours})
        return windows

    @staticmethod
    def _fit_slope_mgdl_per_hour(readings: List[GlucoseReading]) -> Optional[float]:
        """Least-squares glucose slope (mg/dL per hour) over a set of readings."""
        if len(readings) < 3:
            return None
        t0 = readings[0].timestamp
        xs = np.array([(r.timestamp - t0).total_seconds() / 3600.0 for r in readings])
        ys = np.array([r.value for r in readings])
        if np.all(xs == xs[0]):
            return None
        slope, _intercept = np.polyfit(xs, ys, 1)
        return float(slope)

    def compute_basal_drift(
        self,
        hour_range: Tuple[int, int],
        min_hours: float = 5.0,
        active_insulin_time: float = 4.0,
    ) -> Dict:
        """Classify basal need direction for a time segment via steady drift
        in clean (meal/bolus-free) windows overlapping that segment's hours.

        A steady rise means basal is too low for that block; a steady fall
        means it's too high. Only a spike/dip tied to food or a bolus would
        be excluded already (that's what "clean window" means) -- this is
        the "true basal" check from Step 2, evaluated per current segment.
        """
        clean_windows = self.find_clean_windows(min_hours=min_hours, active_insulin_time=active_insulin_time)
        start_h, end_h = hour_range
        segment_span_hours = end_h - start_h

        slopes = []
        for window in clean_windows:
            day = window["start"].date() - timedelta(days=1)
            last_day = window["end"].date() + timedelta(days=1)
            while day <= last_day:
                seg_start = datetime.combine(day, datetime.min.time()) + timedelta(hours=start_h)
                seg_end = seg_start + timedelta(hours=segment_span_hours)
                overlap_start = max(window["start"], seg_start)
                overlap_end = min(window["end"], seg_end)
                if (overlap_end - overlap_start).total_seconds() / 3600.0 >= 1.0:
                    overlap_readings = self._readings_in_range(overlap_start, overlap_end)
                    slope = self._fit_slope_mgdl_per_hour(overlap_readings)
                    if slope is not None:
                        slopes.append(slope)
                day += timedelta(days=1)

        rising = [s for s in slopes if s > self.BASAL_DRIFT_THRESHOLD_MGDL_PER_HR]
        falling = [s for s in slopes if s < -self.BASAL_DRIFT_THRESHOLD_MGDL_PER_HR]

        if len(rising) >= self.MIN_PATTERN_INSTANCES and len(rising) >= len(falling):
            direction, agreeing = "rising", rising
        elif len(falling) >= self.MIN_PATTERN_INSTANCES:
            direction, agreeing = "falling", falling
        elif rising or falling:
            direction = "rising" if len(rising) >= len(falling) else "falling"
            agreeing = rising if direction == "rising" else falling
        else:
            direction, agreeing = "stable", []

        return {
            "n_instances": len(slopes),
            "n_rising": len(rising),
            "n_falling": len(falling),
            "n_stable": len(slopes) - len(rising) - len(falling),
            "direction": direction,
            "median_slope": float(np.median(agreeing)) if agreeing else None,
            "sufficient_evidence": len(agreeing) >= self.MIN_PATTERN_INSTANCES,
        }

    def analyze_meal_response_for_icr(
        self,
        pre_meal_range: Tuple[float, float] = (70.0, 180.0),
        crash_window_hours: Tuple[float, float] = (2.0, 3.0),
        still_high_check_hour: float = 3.0,
        still_high_tolerance_hours: float = 0.5,
        target_max: float = 180.0,
        spike_threshold: float = 50.0,
    ) -> List[Dict]:
        """Classify each meal's post-meal response for carb-ratio tuning.

        Only meals where pre-meal BG was already in range are evaluated --
        an off-baseline starting point contaminates the read on whether the
        ratio itself is right (this also stands in for "accurate carb
        counting and pre-bolusing", which can't be verified directly from
        CGM data alone).

        Ideal: glucose rises after the meal but is back in target range by
        the 3-4h mark, without going dangerously low. Two failure patterns,
        checked in the guide's own windows rather than one generic post-meal
        range:
        - Crashing: any low (<70) within 2-3h of eating -> too_strong (the
          ratio delivers too much insulin per gram; weaken it).
        - Spiking and staying high: glucose spiked (a genuine peak, not
          carb-counting noise) and is still elevated at the 3h mark ->
          too_weak (the ratio delivers too little insulin per gram;
          strengthen it).
        """
        results = []
        for meal in self.data.meals:
            pre_readings = self._readings_in_range(meal.timestamp - timedelta(minutes=30), meal.timestamp)
            if not pre_readings:
                continue
            pre_meal_glucose = float(np.mean([r.value for r in pre_readings]))
            if not (pre_meal_range[0] <= pre_meal_glucose <= pre_meal_range[1]):
                continue

            crash_start = meal.timestamp + timedelta(hours=crash_window_hours[0])
            crash_end = meal.timestamp + timedelta(hours=crash_window_hours[1])
            crash_readings = self._readings_in_range(crash_start, crash_end)

            check_start = meal.timestamp + timedelta(hours=still_high_check_hour - still_high_tolerance_hours)
            check_end = meal.timestamp + timedelta(hours=still_high_check_hour + still_high_tolerance_hours)
            still_high_readings = self._readings_in_range(check_start, check_end)

            if not crash_readings and not still_high_readings:
                continue  # nothing to evaluate this meal against

            peak_window_end = meal.timestamp + timedelta(hours=still_high_check_hour)
            peak_window_readings = self._readings_in_range(meal.timestamp, peak_window_end)
            peak = max((r.value for r in peak_window_readings), default=pre_meal_glucose)

            if crash_readings and any(r.value < 70.0 for r in crash_readings):
                classification = "too_strong"
            elif (
                still_high_readings
                and peak > target_max + spike_threshold
                and min(r.value for r in still_high_readings) > target_max
            ):
                classification = "too_weak"
            else:
                classification = "ok"

            results.append({
                "meal_time": meal.timestamp,
                "carbs": meal.carbs,
                "pre_meal_glucose": pre_meal_glucose,
                "peak_glucose": peak,
                "glucose_at_3h": (
                    float(np.mean([r.value for r in still_high_readings])) if still_high_readings else None
                ),
                "classification": classification,
            })

        return results

    def analyze_correction_only_events(
        self,
        exclude_meal_hours: float = 3.0,
        post_window_hours: Tuple[float, float] = (3.0, 4.0),
        target_max: float = 180.0,
    ) -> List[Dict]:
        """Classify correction-only boluses (no carbs, not near a meal) for
        ISF/correction-factor tuning -- isolates insulin sensitivity alone,
        not food response. Still elevated 3-4h later means the factor is
        too weak (needs a lower number, more aggressive correction); a low
        in that window means it's too strong.
        """
        meal_times = sorted(m.timestamp for m in self.data.meals)
        delta = timedelta(hours=exclude_meal_hours)

        results = []
        for event in self.data.insulin_events:
            if event.event_type != "bolus":
                continue

            idx = bisect.bisect_left(meal_times, event.timestamp)
            near_meal = (
                (idx < len(meal_times) and meal_times[idx] - event.timestamp <= delta)
                or (idx > 0 and event.timestamp - meal_times[idx - 1] <= delta)
            )
            if near_meal:
                continue

            pre_readings = self._readings_in_range(event.timestamp - timedelta(minutes=15), event.timestamp)
            if not pre_readings:
                continue
            pre_bolus_glucose = float(np.mean([r.value for r in pre_readings]))

            window_start = event.timestamp + timedelta(hours=post_window_hours[0])
            window_end = event.timestamp + timedelta(hours=post_window_hours[1])
            window_readings = self._readings_in_range(window_start, window_end)
            if not window_readings:
                continue

            window_min = min(r.value for r in window_readings)

            if window_min < 70.0:
                classification = "too_strong"
            elif window_min > target_max:
                classification = "too_weak"
            else:
                classification = "ok"

            results.append({
                "time": event.timestamp,
                "correction_dose": event.amount,
                "pre_bolus_glucose": pre_bolus_glucose,
                "post_window_min": window_min,
                "classification": classification,
            })

        return results

    def compute_daily_tir_by_hour_range(
        self,
        hour_range: Tuple[int, int],
        target_min: float = 70.0,
        target_max: float = 180.0,
    ) -> List[Dict]:
        """Per-day (not just aggregate) below/in-range/above breakdown
        restricted to an hour range, so a target-segment finding can require
        the same lows-dominant or highs-dominant pattern on multiple
        distinct days rather than being driven by one bad day.
        """
        hours = set(hours_in_range(*hour_range))

        by_day: Dict = {}
        for reading in self.readings:
            if reading.timestamp.hour not in hours:
                continue
            by_day.setdefault(reading.timestamp.date(), []).append(reading.value)

        results = []
        for day, values in sorted(by_day.items()):
            total = len(values)
            below = sum(1 for v in values if v < target_min)
            above = sum(1 for v in values if v > target_max)
            results.append({
                "day": day,
                "n": total,
                "below_pct": 100 * below / total,
                "above_pct": 100 * above / total,
                "in_range_pct": 100 * (total - below - above) / total,
            })

        return results
