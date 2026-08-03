"""Generate Omnipod pump setting recommendations based on glucose analysis."""

from typing import Dict, List, Optional
from .models import (
    OmnipodSettings, BasalProfile, InsulinSensitivityFactor,
    CarbRatio, GloocolData
)
from .analysis import GlucoseAnalyzer
from .segments import segment_ranges, hours_in_range


class OmnipodRecommendationEngine:
    """Generate personalized Omnipod pump recommendations.

    Where possible, ISF and carb ratio use the standard rapid-acting-insulin
    "1800 rule" and "500 rule" (based on total daily dose), with CGM-derived
    signals applied only as bounded adjustments on top — not as the primary
    estimator. When dosing history isn't available, methods fall back to
    conservative, clearly-flagged estimates rather than guessing.
    """

    # Standard clinical rules of thumb for rapid-acting insulin (Humalog,
    # Novolog, Fiasp, etc. — what Omnipod delivers).
    ISF_RULE_CONSTANT = 1800.0
    CARB_RATIO_RULE_CONSTANT = 500.0

    DEFAULT_BASAL_BOLUS_SPLIT = 0.5  # assumed when event types aren't tagged
    MAX_BOLUS_FRACTION_OF_TDD = 0.3
    MAX_BASAL_SAFETY_MULTIPLIER = 2.5

    # Omnipod hardware limits — clamps exist to catch nonsensical values,
    # not to impose a "safe" floor regardless of the patient's actual dosing.
    OMNIPOD_MAX_BOLUS_UNITS = 30.0
    OMNIPOD_MAX_BASAL_UNITS_PER_HOUR = 30.0
    MIN_MAX_BOLUS_UNITS = 1.0
    MIN_MAX_BASAL_UNITS_PER_HOUR = 0.05

    MIN_CLEAN_POINTS_PER_HOUR = 3  # clean basal-signal points needed to trust an hour
    ISF_TIME_OF_DAY_BOUND = 0.15  # +-15%
    CARB_RATIO_TIME_OF_DAY_BOUND = 0.20  # +-20%
    BASAL_SHAPE_BOUND = 0.30  # +-30%

    # Baseline-relative (pattern-based) tuning, used when current_settings is
    # supplied -- see the *_from_baseline methods below. Thresholds/step size
    # follow the "Rule of Three" and "10-20%, small steps" guidance for
    # proposing incremental pump setting changes from CGM data.
    ADJUSTMENT_STEP_FRACTION = 0.15  # +-15% per proposed change, single step
    TARGET_ADJUSTMENT_STEP_MGDL = 10.0  # target is near-absolute, not scaled by %

    def __init__(
        self,
        data: GloocolData,
        active_insulin_time: float = 4.0,
        current_settings: Optional[Dict] = None,
    ):
        """Initialize with Glooko data.

        active_insulin_time is a pass-through of the patient's configured
        duration of insulin action (hours) -- it's a clinical/pharmacokinetic
        setting, not something this engine derives from CGM data. It's used
        to define the meal/bolus exclusion windows for basal-need inference,
        and is echoed on the resulting OmnipodSettings.

        current_settings, when provided (schema: data/sample_current_settings.json),
        switches generate_recommendations() to a baseline-relative, evidence-gated
        methodology: each current segment is evaluated for a repeatable pattern
        (>=3 independent instances) and adjusted by a small bounded step only
        when one is found, rather than computed from scratch via a population
        formula. Without it, generate_recommendations() falls back to the
        TDD-based population-rule approach.
        """
        self.data = data
        self.active_insulin_time = active_insulin_time
        self.current_settings = current_settings
        self.analyzer = GlucoseAnalyzer(data)
        self._last_findings: List[Dict] = []

    def generate_recommendations(self) -> OmnipodSettings:
        """Generate complete Omnipod settings recommendations.

        Uses the baseline-relative, evidence-gated methodology when
        current_settings was supplied to the constructor; otherwise falls
        back to the TDD-based population-rule approach. Either way, also
        populates the findings report retrievable via generate_findings_report()
        (empty when no current_settings was given -- baseline-relative
        findings can't exist without a baseline).
        """
        warnings: List[str] = []
        findings: List[Dict] = []

        stats = self.analyzer.get_statistics()
        tir = self.analyzer.get_time_in_range()
        tdd = self.analyzer.get_total_daily_dose()
        sufficiency = self.analyzer.assess_data_sufficiency()

        self._add_data_quality_warnings(sufficiency, tdd, warnings)

        target_min = self._estimate_target_min(tir)
        target_max = self._estimate_target_max(tir)

        if self.current_settings:
            basal_profile = self._generate_basal_profile_from_baseline(
                self.current_settings, warnings, findings
            )
            isf = self._generate_isf_from_baseline(self.current_settings, warnings, findings)
            carb_ratio = self._generate_carb_ratio_from_baseline(
                self.current_settings, warnings, findings
            )
            self._analyze_target_segments(self.current_settings, target_min, target_max, findings)

            if "max_bolus" in self.current_settings:
                max_bolus = self.current_settings["max_bolus"]
            else:
                max_bolus = self._estimate_max_bolus(tdd, warnings)

            if "max_basal" in self.current_settings:
                max_basal = self.current_settings["max_basal"]
            else:
                max_basal = self._estimate_max_basal(basal_profile)
        else:
            hourly_avgs = self.analyzer.get_hourly_averages()
            basal_signal = self.analyzer.get_basal_requirements_by_hour(
                active_insulin_time=self.active_insulin_time
            )
            meal_patterns = self.analyzer.detect_meal_response_pattern()
            basal_bolus_split = self.analyzer.get_basal_bolus_split()

            basal_profile = self._generate_basal_profile(basal_signal, tdd, basal_bolus_split, warnings)
            isf = self._generate_isf(stats, hourly_avgs, tdd, warnings)
            carb_ratio = self._generate_carb_ratio(meal_patterns, tdd, warnings)
            max_bolus = self._estimate_max_bolus(tdd, warnings)
            max_basal = self._estimate_max_basal(basal_profile)

        self._last_findings = findings

        settings = OmnipodSettings(
            basal_profile=basal_profile,
            insulin_sensitivity_factor=isf,
            carb_ratio=carb_ratio,
            target_glucose_min=target_min,
            target_glucose_max=target_max,
            correction_target=self._estimate_correction_target(stats, target_min, target_max),
            max_bolus=max_bolus,
            max_basal=max_basal,
            active_insulin_time=self.active_insulin_time,
            warnings=warnings,
        )

        return settings

    def generate_findings_report(self) -> List[Dict]:
        """The baseline-relative "Quick Proposal Template": one row per
        setting+segment with a finding, ordered Basal -> ICR -> CF -> Target
        (the recommended tuning sequence -- address basal first, since a
        basal fix changes the baseline everything else is judged against).

        Each row: {setting, time_block, current_value, pattern_observed,
        proposed_direction, proposed_value, magnitude_pct, confidence,
        what_to_watch}. Populated as a side effect of generate_recommendations();
        empty if no current_settings were supplied, since these findings are
        inherently relative to a baseline.
        """
        order = {
            "Basal": 0,
            "Insulin-to-Carb Ratio (ICR)": 1,
            "Correction Factor / Sensitivity (ISF)": 2,
            "Target Glucose (BGT)": 3,
        }
        return sorted(
            self._last_findings,
            key=lambda f: (order.get(f["setting"], 99), f["time_block"]),
        )

    def _add_data_quality_warnings(self, sufficiency: Dict, tdd: Optional[float], warnings: List[str]) -> None:
        if not sufficiency["is_sufficient"]:
            warnings.append(
                f"Only {sufficiency['days_covered']} day(s) of glucose data available "
                f"(recommend at least {GlucoseAnalyzer.MIN_SUFFICIENT_DAYS}+, ideally 14+). "
                "All recommendations below are low-confidence."
            )
        if sufficiency["excluded_readings"]:
            warnings.append(
                f"Excluded {sufficiency['excluded_readings']} glucose reading(s) outside the "
                f"physiologically plausible range ({GlucoseAnalyzer.MIN_VALID_GLUCOSE:.0f}-"
                f"{GlucoseAnalyzer.MAX_VALID_GLUCOSE:.0f} mg/dL) as likely sensor errors."
            )
        if tdd is None:
            warnings.append(
                "No insulin dosing history found; ISF, carb ratio, basal profile, and max "
                "bolus fall back to conservative generic estimates rather than dose-based "
                "calculations. Provide insulin event data for personalized recommendations."
            )

    def _generate_basal_profile(
        self,
        basal_signal: Dict[int, Dict],
        tdd: Optional[float],
        basal_bolus_split: Optional[Dict[str, float]],
        warnings: List[str],
    ) -> BasalProfile:
        """Generate hourly basal rate profile.

        Baseline daily basal total comes from total daily dose (TDD) apportioned
        by the observed or assumed basal/bolus split, spread flat across 24h.
        The standard time-of-day shape and any clean-window CGM signal are then
        applied as a bounded adjustment on top of that baseline, not as a
        replacement for it.
        """
        if tdd is not None and tdd > 0:
            basal_fraction = (
                basal_bolus_split["basal_fraction"] if basal_bolus_split
                else self.DEFAULT_BASAL_BOLUS_SPLIT
            )
            flat_baseline = (tdd * basal_fraction) / 24.0
        else:
            flat_baseline = 0.5  # generic population default

        time_of_day_multiplier = self._basal_time_of_day_multiplier()

        rates = {}
        low_confidence_hours = 0
        for hour in range(24):
            shape = time_of_day_multiplier[hour]
            info = basal_signal.get(hour, {"signal": None, "clean_points": 0})

            if info["signal"] is not None and info["clean_points"] >= self.MIN_CLEAN_POINTS_PER_HOUR:
                observed_ratio = info["signal"] / flat_baseline if flat_baseline > 0 else 1.0
                bounded_ratio = min(
                    1 + self.BASAL_SHAPE_BOUND,
                    max(1 - self.BASAL_SHAPE_BOUND, observed_ratio),
                )
                adjusted_rate = flat_baseline * shape * bounded_ratio
            else:
                adjusted_rate = flat_baseline * shape
                low_confidence_hours += 1

            rates[hour] = round(max(0.05, adjusted_rate), 2)

        if low_confidence_hours:
            warnings.append(
                f"{low_confidence_hours} of 24 basal hour(s) had too few clean "
                "(meal/bolus-free) CGM windows to estimate individually; the "
                "population-average shape was used for those hours."
            )

        return BasalProfile(name="Recommended Basal Profile", rates=rates)

    @staticmethod
    def _basal_time_of_day_multiplier() -> Dict[int, float]:
        multiplier = {}
        for hour in range(24):
            if 22 <= hour or hour < 6:  # Night: typically lower basal
                multiplier[hour] = 0.8
            elif 6 <= hour < 12:  # Morning: often requires higher basal
                multiplier[hour] = 1.1
            elif 12 <= hour < 18:  # Afternoon
                multiplier[hour] = 1.0
            else:  # Evening
                multiplier[hour] = 1.05
        return multiplier

    def _generate_isf(
        self,
        stats: Dict,
        hourly_avgs: Dict,
        tdd: Optional[float],
        warnings: List[str],
    ) -> InsulinSensitivityFactor:
        """Generate insulin sensitivity factor (1:X correction factor).

        Uses the standard "1800 rule" (1800 / TDD) for rapid-acting insulin
        when dosing history is available. Time-of-day adjustment (dawn
        phenomenon, overnight sensitivity) is a bounded multiplier on top of
        that baseline, not a re-derivation from the current glucose level.
        """
        if not stats:
            return InsulinSensitivityFactor(name="Recommended ISF", factors={h: 100.0 for h in range(24)})

        mean_glucose = stats.get("mean", 150)
        baseline = self.ISF_RULE_CONSTANT / tdd if (tdd is not None and tdd > 0) else None

        if baseline is None:
            warnings.append(
                "ISF estimated from current glucose levels rather than total daily "
                "dose (no insulin dosing history available) — lower confidence."
            )

        factors = {}
        for hour in range(24):
            multiplier = self._isf_time_of_day_multiplier(hour)

            if baseline is not None:
                factors[hour] = round(baseline * multiplier, 1)
            else:
                hourly_avg = hourly_avgs.get(hour, mean_glucose)
                if hourly_avg < 100:
                    base_isf = 85
                elif hourly_avg < 150:
                    base_isf = 100
                elif hourly_avg < 200:
                    base_isf = 115
                else:
                    base_isf = 130
                factors[hour] = round(base_isf * multiplier, 1)

        return InsulinSensitivityFactor(name="Recommended ISF", factors=factors)

    def _isf_time_of_day_multiplier(self, hour: int) -> float:
        if 4 <= hour < 8:  # Dawn phenomenon: more insulin needed -> lower ISF
            return 1 - self.ISF_TIME_OF_DAY_BOUND
        if 22 <= hour or hour < 2:  # Night: less insulin needed -> higher ISF
            return 1 + self.ISF_TIME_OF_DAY_BOUND
        return 1.0

    def _generate_carb_ratio(
        self,
        meal_patterns: list,
        tdd: Optional[float],
        warnings: List[str],
    ) -> CarbRatio:
        """Generate carb-to-insulin ratio.

        Uses the standard "500 rule" (500 / TDD) for rapid-acting insulin when
        dosing history is available; observed meal-response data is applied
        only as a bounded modifier on top of that baseline. Falls back to a
        meal-response-only estimate, or a generic default, when TDD is
        unavailable.
        """
        observed_ratio = self._estimate_carb_ratio_from_meals(meal_patterns)

        if tdd is not None and tdd > 0:
            baseline = self._clamp_carb_ratio(self.CARB_RATIO_RULE_CONSTANT / tdd)
            if observed_ratio is not None:
                relative = observed_ratio / baseline
                bounded = min(
                    1 + self.CARB_RATIO_TIME_OF_DAY_BOUND,
                    max(1 - self.CARB_RATIO_TIME_OF_DAY_BOUND, relative),
                )
                baseline = baseline * bounded
        elif observed_ratio is not None:
            baseline = observed_ratio
            warnings.append(
                "No insulin dosing history found; carb ratio was estimated from "
                "meal-response CGM data only — lower confidence than a dose-based "
                "calculation."
            )
        else:
            baseline = 15.0
            warnings.append(
                "No insulin dosing history or usable meal-response data found; carb "
                "ratio uses a generic default (1 unit per 15g) rather than a "
                "personalized estimate."
            )

        ratios = {}
        for hour in range(24):
            if 6 <= hour < 12:  # Morning: often more insulin resistant
                ratios[hour] = round(baseline * 0.85, 1)
            elif 12 <= hour < 18:  # Afternoon
                ratios[hour] = round(baseline, 1)
            else:  # Evening and night: more insulin sensitive
                ratios[hour] = round(baseline * 1.1, 1)

        return CarbRatio(name="Recommended Carb Ratio", ratios=ratios)

    @staticmethod
    def _clamp_carb_ratio(ratio: float) -> float:
        return max(3.0, min(50.0, ratio))

    def _estimate_carb_ratio_from_meals(self, meal_patterns: list) -> Optional[float]:
        """Estimate carb ratio purely from observed meal glucose response."""
        carb_events = [p for p in meal_patterns if p.get("carbs", 0) > 0]
        if not carb_events:
            return None

        avg_carbs = sum(p["carbs"] for p in carb_events) / len(carb_events)
        avg_rise = sum(p.get("glucose_rise", 0) for p in carb_events) / len(carb_events)
        if avg_rise <= 0:
            return None

        base_ratio = avg_carbs / (avg_rise / 50)
        return self._clamp_carb_ratio(base_ratio)

    def _estimate_target_min(self, tir: Dict) -> float:
        """Estimate minimum target glucose."""
        # Standard range: 70 mg/dL
        # Could be adjusted based on patient profile, but 70 is safe default
        return 70.0

    def _estimate_target_max(self, tir: Dict) -> float:
        """Estimate maximum target glucose."""
        # Standard range: 180 mg/dL for most patients
        # Could be adjusted based on individual goals
        return 180.0

    def _estimate_correction_target(self, stats: Dict, target_min: float, target_max: float) -> float:
        """Estimate glucose correction target.

        Always clamped to stay comfortably above target_min, so a low mean
        glucose (e.g. from a patient already running low) can never pull the
        correction target down toward or below the hypoglycemia threshold.
        """
        if not stats:
            candidate = 120.0
        else:
            mean = stats.get("mean", 150)
            candidate = mean - 10 if mean < 120 else 120.0

        lower_bound = target_min + 10
        return min(target_max, max(lower_bound, candidate))

    def _estimate_max_bolus(self, tdd: Optional[float], warnings: List[str]) -> float:
        """Estimate maximum bolus allowed.

        Derived from total daily dose (a single bolus rarely exceeds ~30% of
        TDD in normal dosing) rather than a flat value — a fixed ceiling is
        not "safe" for a low-dose patient, it's just a large number.
        """
        if tdd is None or tdd <= 0:
            warnings.append(
                "No insulin dosing history found; max bolus uses a conservative "
                "generic default rather than a dose-based estimate. This MUST be "
                "reviewed and set by a clinician before use."
            )
            return self.MIN_MAX_BOLUS_UNITS * 10  # conservative generic default (10u)

        estimated = tdd * self.MAX_BOLUS_FRACTION_OF_TDD
        return round(min(self.OMNIPOD_MAX_BOLUS_UNITS, max(self.MIN_MAX_BOLUS_UNITS, estimated)), 1)

    def _estimate_max_basal(self, basal_profile: BasalProfile) -> float:
        """Estimate maximum basal rate from the computed basal profile's peak hour."""
        peak_hourly = max(basal_profile.rates.values()) if basal_profile.rates else 0.5
        estimated = peak_hourly * self.MAX_BASAL_SAFETY_MULTIPLIER
        return round(
            min(self.OMNIPOD_MAX_BASAL_UNITS_PER_HOUR, max(self.MIN_MAX_BASAL_UNITS_PER_HOUR, estimated)),
            2,
        )

    @staticmethod
    def _sorted_segments_with_ranges(segments: List[Dict]):
        ranges = segment_ranges(segments)
        ordered = sorted(segments, key=lambda s: s["start_hour"])
        return zip(ordered, ranges)

    @staticmethod
    def _format_time_block(start_h: int, end_h: int) -> str:
        """e.g. (0, 24) -> '00:00-24:00', not '00:00-00:00' -- end_h % 24
        would otherwise wrap a full-day segment's end back to midnight."""
        end_display = end_h % 24
        if end_display == 0 and end_h > start_h:
            end_display = 24
        return f"{start_h:02d}:00-{end_display:02d}:00"

    @staticmethod
    def _basal_evidence(instances: List[Dict]) -> List[Dict]:
        """Concrete per-night evidence rows for a basal drift finding."""
        return [
            {
                "date": inst["date"].isoformat(),
                "time_start": inst["window_start"].strftime("%H:%M"),
                "bg_start": round(inst["bg_start"], 1),
                "time_end": inst["window_end"].strftime("%H:%M"),
                "bg_end": round(inst["bg_end"], 1),
                "slope_mgdl_per_hr": round(inst["slope"], 1),
            }
            for inst in sorted(instances, key=lambda i: i["date"])
        ]

    @staticmethod
    def _meal_evidence(meals: List[Dict]) -> List[Dict]:
        """Concrete per-meal evidence rows for an ICR finding."""
        return [
            {
                "date": m["meal_time"].date().isoformat(),
                "time": m["meal_time"].strftime("%H:%M"),
                "carbs": m["carbs"],
                "bg_before": round(m["pre_meal_glucose"], 1),
                "bg_after": round(
                    m["glucose_at_3h"] if m["glucose_at_3h"] is not None else m["peak_glucose"], 1
                ),
            }
            for m in sorted(meals, key=lambda m: m["meal_time"])
        ]

    @staticmethod
    def _correction_event_evidence(events: List[Dict]) -> List[Dict]:
        """Concrete per-event evidence rows for a CF/ISF finding."""
        return [
            {
                "date": e["time"].date().isoformat(),
                "time": e["time"].strftime("%H:%M"),
                "correction_dose": e["correction_dose"],
                "bg_before": round(e["pre_bolus_glucose"], 1),
                "bg_after": round(e["post_window_min"], 1),
            }
            for e in sorted(events, key=lambda e: e["time"])
        ]

    @staticmethod
    def _daily_tir_evidence(days: List[Dict]) -> List[Dict]:
        """Concrete per-day evidence rows for a target-glucose finding."""
        return [
            {
                "date": d["day"].isoformat(),
                "below_pct": round(d["below_pct"], 1),
                "above_pct": round(d["above_pct"], 1),
            }
            for d in sorted(days, key=lambda d: d["day"])
        ]

    def _generate_basal_profile_from_baseline(
        self, current_settings: Dict, warnings: List[str], findings: List[Dict]
    ) -> BasalProfile:
        """Evaluate each current basal segment for steady drift in clean
        (meal/bolus-free) windows -- rise means basal too low, fall means
        too high -- and adjust by a bounded step only when the pattern
        repeats across >=3 independent windows. Segments without a
        supported direction keep their current rate.
        """
        segments = current_settings.get("basal_segments") or []
        if not segments:
            warnings.append(
                "No current basal segments provided; cannot run baseline-relative "
                "basal analysis."
            )
            return BasalProfile(name="Recommended Basal Profile", rates={h: 0.5 for h in range(24)})

        rates: Dict[int, float] = {}
        segments_with_findings = 0

        for seg, (start_h, end_h) in self._sorted_segments_with_ranges(segments):
            current_rate = seg["rate"]
            time_block = self._format_time_block(start_h, end_h)
            drift = self.analyzer.compute_basal_drift((start_h, end_h))

            if drift["sufficient_evidence"] and drift["direction"] in ("rising", "falling"):
                segments_with_findings += 1
                direction = "raise" if drift["direction"] == "rising" else "lower"
                factor = 1 + self.ADJUSTMENT_STEP_FRACTION if direction == "raise" else 1 - self.ADJUSTMENT_STEP_FRACTION
                new_rate = round(current_rate * factor, 2)
                agreeing = max(drift["n_rising"], drift["n_falling"])
                findings.append({
                    "setting": "Basal",
                    "time_block": time_block,
                    "current_value": current_rate,
                    "pattern_observed": (
                        f"Glucose drifted {drift['direction']} at a median "
                        f"{abs(drift['median_slope']):.1f} mg/dL/hr across "
                        f"{drift['n_instances']} clean window(s) evaluated, "
                        f"{agreeing} agreeing on direction."
                    ),
                    "proposed_direction": direction,
                    "proposed_value": new_rate,
                    "magnitude_pct": round(self.ADJUSTMENT_STEP_FRACTION * 100, 1),
                    "confidence": f"supported (n={agreeing})",
                    "what_to_watch": (
                        "Re-check this window in 3-5 days; watch for a new low or high "
                        "cluster shifting into an adjacent time block."
                    ),
                    "evidence": self._basal_evidence(drift["instances"]),
                })
            else:
                new_rate = current_rate
                findings.append({
                    "setting": "Basal",
                    "time_block": time_block,
                    "current_value": current_rate,
                    "pattern_observed": (
                        f"{drift['n_instances']} clean window(s) evaluated; no steady "
                        "drift with at least 3 agreeing instances found."
                    ),
                    "proposed_direction": "no change",
                    "proposed_value": current_rate,
                    "magnitude_pct": 0.0,
                    "confidence": "insufficient evidence",
                    "what_to_watch": None,
                    "evidence": self._basal_evidence(drift["instances"]),
                })

            for h in hours_in_range(start_h, end_h):
                rates[h] = round(max(0.05, new_rate), 2)

        if segments_with_findings:
            warnings.append(
                f"Basal drift detected in {segments_with_findings} segment(s) -- per "
                "standard practice, address basal before trusting the ICR/CF/Target "
                "findings below: a basal fix changes the baseline everything else is "
                "judged against."
            )

        return BasalProfile(name="Recommended Basal Profile", rates=rates)

    def _generate_isf_from_baseline(
        self, current_settings: Dict, warnings: List[str], findings: List[Dict]
    ) -> InsulinSensitivityFactor:
        """Evaluate each current ISF segment using isolated correction-only
        bolus events (no meal within 3h): still elevated 3-4h later means
        the factor is too weak (lower the number, more aggressive
        correction); a low in that window means it's too strong (raise the
        number). Requires >=3 agreeing events; isolated correction-only
        events are often rare, and that scarcity itself is reported rather
        than silently proceeding on a thin sample.
        """
        segments = current_settings.get("isf_segments") or []
        if not segments:
            warnings.append(
                "No current ISF segments provided; cannot run baseline-relative "
                "correction-factor analysis."
            )
            return InsulinSensitivityFactor(name="Recommended ISF", factors={h: 100.0 for h in range(24)})

        events = self.analyzer.analyze_correction_only_events()
        factors: Dict[int, float] = {}

        for seg, (start_h, end_h) in self._sorted_segments_with_ranges(segments):
            current_value = seg["value"]
            time_block = self._format_time_block(start_h, end_h)
            hours = set(hours_in_range(start_h, end_h))
            segment_events = [e for e in events if e["time"].hour in hours]

            too_weak = [e for e in segment_events if e["classification"] == "too_weak"]
            too_strong = [e for e in segment_events if e["classification"] == "too_strong"]

            if len(too_weak) >= GlucoseAnalyzer.MIN_PATTERN_INSTANCES and len(too_weak) >= len(too_strong):
                direction, count = "lower", len(too_weak)
            elif len(too_strong) >= GlucoseAnalyzer.MIN_PATTERN_INSTANCES:
                direction, count = "raise", len(too_strong)
            else:
                direction, count = "no change", 0

            if direction == "no change":
                new_value = current_value
                pattern = (
                    f"{len(segment_events)} isolated correction-only event(s) found in "
                    "this window (bolus with no meal within 3h) -- fewer than 3 support "
                    "a direction. Isolated correction-only events are often rare in real "
                    "usage; if this stays sparse, that itself is useful information for "
                    "your clinician (may need an in-clinic ISF test rather than a Glooko "
                    "read)."
                )
                watch = None
                evidence_source = segment_events
            else:
                factor = 1 - self.ADJUSTMENT_STEP_FRACTION if direction == "lower" else 1 + self.ADJUSTMENT_STEP_FRACTION
                new_value = round(current_value * factor, 1)
                verb = "were still elevated" if direction == "lower" else "went low"
                pattern = f"{count} of {len(segment_events)} correction-only event(s) in this window {verb} 3-4h later."
                watch = "Watch for overcorrection lows following a correction bolus in this window."
                evidence_source = too_weak if direction == "lower" else too_strong

            findings.append({
                "setting": "Correction Factor / Sensitivity (ISF)",
                "time_block": time_block,
                "current_value": current_value,
                "pattern_observed": pattern,
                "proposed_direction": direction,
                "proposed_value": new_value,
                "evidence": self._correction_event_evidence(evidence_source),
                "magnitude_pct": round(self.ADJUSTMENT_STEP_FRACTION * 100, 1) if direction != "no change" else 0.0,
                "confidence": f"supported (n={count})" if direction != "no change" else "insufficient evidence",
                "what_to_watch": watch,
            })

            for h in hours:
                factors[h] = new_value

        return InsulinSensitivityFactor(name="Recommended ISF", factors=factors)

    def _generate_carb_ratio_from_baseline(
        self, current_settings: Dict, warnings: List[str], findings: List[Dict]
    ) -> CarbRatio:
        """Evaluate each current carb-ratio segment using meals with in-range
        pre-meal BG: a genuine spike still elevated at the 3h mark means the
        ratio is too weak (lower the number, stronger ratio, more insulin
        per gram); a crash within 2-3h means it's too strong (raise the
        number, weaker ratio). Requires >=3 agreeing meals.
        """
        segments = current_settings.get("carb_ratio_segments") or []
        if not segments:
            warnings.append(
                "No current carb ratio segments provided; cannot run baseline-relative "
                "ICR analysis."
            )
            return CarbRatio(name="Recommended Carb Ratio", ratios={h: 15.0 for h in range(24)})

        meal_responses = self.analyzer.analyze_meal_response_for_icr()
        ratios: Dict[int, float] = {}

        for seg, (start_h, end_h) in self._sorted_segments_with_ranges(segments):
            current_value = seg["value"]
            time_block = self._format_time_block(start_h, end_h)
            hours = set(hours_in_range(start_h, end_h))
            segment_meals = [m for m in meal_responses if m["meal_time"].hour in hours]

            too_weak = [m for m in segment_meals if m["classification"] == "too_weak"]
            too_strong = [m for m in segment_meals if m["classification"] == "too_strong"]

            if len(too_weak) >= GlucoseAnalyzer.MIN_PATTERN_INSTANCES and len(too_weak) >= len(too_strong):
                direction, count = "lower", len(too_weak)
            elif len(too_strong) >= GlucoseAnalyzer.MIN_PATTERN_INSTANCES:
                direction, count = "raise", len(too_strong)
            else:
                direction, count = "no change", 0

            if direction == "no change":
                new_value = current_value
                pattern = (
                    f"{len(segment_meals)} meal(s) with in-range pre-meal BG evaluated "
                    "in this window -- fewer than 3 support a direction."
                )
                watch = None
                evidence_source = segment_meals
            else:
                factor = 1 - self.ADJUSTMENT_STEP_FRACTION if direction == "lower" else 1 + self.ADJUSTMENT_STEP_FRACTION
                new_value = self._clamp_carb_ratio(round(current_value * factor, 1))
                verb = (
                    "spiked and was still high at the 3h mark" if direction == "lower"
                    else "crashed low within 2-3h of eating"
                )
                pattern = f"{count} of {len(segment_meals)} qualifying meal(s) in this window {verb}."
                watch = (
                    "Watch for a new low cluster after tightening."
                    if direction == "lower" else
                    "Watch for the post-meal spike returning after loosening."
                )
                evidence_source = too_weak if direction == "lower" else too_strong

            findings.append({
                "setting": "Insulin-to-Carb Ratio (ICR)",
                "time_block": time_block,
                "current_value": current_value,
                "pattern_observed": pattern,
                "evidence": self._meal_evidence(evidence_source),
                "proposed_direction": direction,
                "proposed_value": new_value,
                "magnitude_pct": round(self.ADJUSTMENT_STEP_FRACTION * 100, 1) if direction != "no change" else 0.0,
                "confidence": f"supported (n={count})" if direction != "no change" else "insufficient evidence",
                "what_to_watch": watch,
            })

            for h in hours:
                ratios[h] = new_value

        return CarbRatio(name="Recommended Carb Ratio", ratios=ratios)

    def _analyze_target_segments(
        self,
        current_settings: Dict,
        target_min: float,
        target_max: float,
        findings: List[Dict],
    ) -> None:
        """Evaluate each current target segment's TIR breakdown by time of
        day: lows dominant on >=3 days means the target is too tight (raise
        it, more buffer); highs dominant with minimal lows on >=3 days means
        there's room to tighten (lower it). Informational only -- appended to
        the findings report, since OmnipodSettings' correction_target stays a
        single safety-clamped value rather than a per-segment schedule.
        """
        segments = current_settings.get("target_segments") or []
        if not segments:
            return

        step = self.TARGET_ADJUSTMENT_STEP_MGDL

        for seg, (start_h, end_h) in self._sorted_segments_with_ranges(segments):
            current_value = seg["target"]
            time_block = self._format_time_block(start_h, end_h)
            daily = self.analyzer.compute_daily_tir_by_hour_range((start_h, end_h), target_min, target_max)

            lows_dominant_days = sum(1 for d in daily if d["below_pct"] > 0 and d["below_pct"] >= d["above_pct"])
            highs_dominant_days = sum(1 for d in daily if d["above_pct"] > 0 and d["above_pct"] > d["below_pct"])

            if lows_dominant_days >= GlucoseAnalyzer.MIN_PATTERN_INSTANCES and lows_dominant_days >= highs_dominant_days:
                direction, count, delta = "raise", lows_dominant_days, step
            elif highs_dominant_days >= GlucoseAnalyzer.MIN_PATTERN_INSTANCES:
                direction, count, delta = "lower", highs_dominant_days, -step
            else:
                direction, count, delta = "no change", 0, 0.0

            if direction == "no change":
                new_value = current_value
                pattern = (
                    f"{len(daily)} day(s) with data evaluated in this window; no "
                    "consistent lows- or highs-dominant pattern on 3+ days."
                )
                watch = None
                evidence_source = daily
            else:
                new_value = min(target_max, max(target_min + 10, current_value + delta))
                dominant = "lows" if direction == "raise" else "highs"
                pattern = f"{count} of {len(daily)} day(s) with data in this window were {dominant}-dominant."
                watch = (
                    "Target interacts with both ICR and CF -- re-check this window last, "
                    "after basal/ICR/CF changes have settled."
                )
                evidence_source = (
                    [d for d in daily if d["below_pct"] > 0 and d["below_pct"] >= d["above_pct"]]
                    if direction == "raise" else
                    [d for d in daily if d["above_pct"] > 0 and d["above_pct"] > d["below_pct"]]
                )

            findings.append({
                "setting": "Target Glucose (BGT)",
                "time_block": time_block,
                "current_value": current_value,
                "pattern_observed": pattern,
                "evidence": self._daily_tir_evidence(evidence_source),
                "proposed_direction": direction,
                "proposed_value": new_value,
                "magnitude_pct": None,
                "confidence": f"supported (n={count})" if direction != "no change" else "insufficient evidence",
                "what_to_watch": watch,
            })

    def generate_summary_report(self) -> Dict:
        """Generate a summary report of analysis and recommendations."""
        stats = self.analyzer.get_statistics()
        tir = self.analyzer.get_time_in_range()
        meal_patterns = self.analyzer.detect_meal_response_pattern()
        low_events = self.analyzer.detect_low_glucose_events()

        return {
            "data_summary": {
                "total_readings": len(self.data.glucose_readings),
                "total_meals": len(self.data.meals),
                "total_insulin_events": len(self.data.insulin_events),
                "date_range": self._get_date_range(),
            },
            "data_quality": self.analyzer.assess_data_sufficiency(),
            "glucose_statistics": stats,
            "time_in_range": tir,
            "glucose_variability": self.analyzer.get_glucose_variability(),
            "meal_patterns_detected": len(meal_patterns),
            "low_glucose_events": len(low_events),
            "recommendations": self.generate_recommendations().to_dict(),
        }

    def _get_date_range(self) -> Dict:
        """Get date range of data."""
        start, end = self.data.get_time_range()
        return {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        }
