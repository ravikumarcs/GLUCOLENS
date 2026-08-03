"""Command-line interface for GlucoLens."""

import argparse
import json
import sys
from pathlib import Path
from .data_loader import GlookoDataLoader
from .recommendation_engine import OmnipodRecommendationEngine
from .comparison import compare_settings
from .constants import DISCLAIMER, AUTOMATED_MODE_NOTE, TUNING_PROCESS_NOTE


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="GlucoLens: Glooko to Omnipod recommendations"
    )
    
    parser.add_argument(
        "input_file",
        help="Path to Glooko CSV or JSON export file"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Output file for recommendations (JSON)",
        default=None
    )
    
    parser.add_argument(
        "-r", "--report",
        help="Generate detailed analysis report",
        action="store_true"
    )
    
    parser.add_argument(
        "-f", "--format",
        choices=["json", "text"],
        default="text",
        help="Output format"
    )

    parser.add_argument(
        "-c", "--compare",
        help=(
            "Path to a JSON file describing the currently-configured pump "
            "settings (see data/sample_current_settings.json); prints a "
            "current-vs-recommended comparison"
        ),
        default=None
    )

    args = parser.parse_args()

    try:
        # Load data
        print(f"Loading data from {args.input_file}...", file=sys.stderr)
        loader = GlookoDataLoader()
        data = loader.load(args.input_file)

        print(f"Loaded {len(data.glucose_readings)} glucose readings, "
              f"{len(data.meals)} meals, {len(data.insulin_events)} insulin events",
              file=sys.stderr)

        current_settings = None
        if args.compare:
            with open(args.compare, 'r') as f:
                current_settings = json.load(f)

        # Generate recommendations
        print("Analyzing glucose patterns...", file=sys.stderr)
        active_insulin_time = (
            current_settings.get("active_insulin_time", 4.0) if current_settings else 4.0
        )
        engine = OmnipodRecommendationEngine(
            data, active_insulin_time=active_insulin_time, current_settings=current_settings
        )

        if args.report:
            report = engine.generate_summary_report()
            output = report
        else:
            recommendations = engine.generate_recommendations()
            output = recommendations.to_dict()

        recommendation_dict = output.get("recommendations", output)
        schedule_proposal = engine.generate_schedule_proposal() if current_settings else {}
        comparison_lines = (
            build_comparison_report(current_settings, recommendation_dict, schedule_proposal)
            if current_settings else []
        )
        findings_lines = (
            build_findings_report(engine.generate_findings_report())
            if current_settings else []
        )

        # Output results
        if args.format == "json":
            output_with_disclaimer = {"disclaimer": DISCLAIMER, **output}
            if comparison_lines:
                output_with_disclaimer["comparison"] = comparison_lines
            if findings_lines:
                output_with_disclaimer["proposal_report"] = {
                    "process_note": TUNING_PROCESS_NOTE,
                    "findings": engine.generate_findings_report(),
                }
            if schedule_proposal:
                output_with_disclaimer["schedule_proposal"] = schedule_proposal
            output_text = json.dumps(output_with_disclaimer, indent=2, default=str)
        else:
            output_text = format_output(output) + "\n\n" + format_disclaimer_block(output)
            if findings_lines:
                output_text += "\n\n" + "\n".join(findings_lines)
            if comparison_lines:
                output_text += "\n\n" + "\n".join(comparison_lines)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output_text)
            print(f"Recommendations saved to {args.output}", file=sys.stderr)
        else:
            print(output_text)
        
        return 0
    
    except FileNotFoundError:
        print(f"Error: File not found: {args.input_file}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def build_comparison_report(current: dict, recommendation: dict, schedule_proposal: dict = None) -> list:
    """Build a current-vs-recommended comparison as a list of text lines,
    covering both comparison modes side by side: today's segment boundaries
    with adjusted values, and the newly-discovered schedule (different
    boundaries, up to 8 segments) if `schedule_proposal` is provided.

    `current` follows the schema in data/sample_current_settings.json.
    `recommendation` is an OmnipodSettings.to_dict() (or the "recommendations"
    sub-dict of a full report).
    """
    comparison = compare_settings(current, recommendation)

    lines = [
        "=" * 60,
        "CURRENT vs RECOMMENDED PUMP SETTINGS",
        "=" * 60,
        "",
        f"NOTE: {AUTOMATED_MODE_NOTE}",
        "",
    ]

    def line(label, cur, rec, unit=""):
        cur_str = f"{cur:g}{unit}" if isinstance(cur, (int, float)) else str(cur)
        rec_str = f"{rec:g}{unit}" if isinstance(rec, (int, float)) else str(rec if rec is not None else "N/A")
        return f"  {label:<12} current {cur_str}  ->  recommended {rec_str}"

    for scalar in comparison["scalars"]:
        lines.append(f"{scalar['label'].upper()} ({scalar['unit']}):")
        lines.append(line("", scalar["current"], scalar["recommended"]))
        lines.append("")

    lines.append("-- SAME TIME SEGMENTS (today's boundaries, adjusted values) --")
    lines.append("")

    if comparison["basal_segments"]:
        lines.append("BASAL RATE (units/hr) by current segment start hour:")
        for seg in comparison["basal_segments"]:
            lines.append(line(f"{seg['hour']:02d}:00", seg["current"], seg["recommended"]))
        lines.append("")

    if comparison["isf_segments"]:
        lines.append("INSULIN SENSITIVITY FACTOR (1:X mg/dL per unit) by current segment start hour:")
        for seg in comparison["isf_segments"]:
            lines.append(line(f"{seg['hour']:02d}:00", seg["current"], seg["recommended"]))
        lines.append("")

    if comparison["carb_ratio_segments"]:
        lines.append("CARB RATIO (g/unit) by current segment start hour:")
        for seg in comparison["carb_ratio_segments"]:
            lines.append(line(f"{seg['hour']:02d}:00", seg["current"], seg["recommended"]))
        lines.append("")

    if comparison["target_segments"]:
        lines.append(
            "TARGET BG (mg/dL) by current segment start hour (this tool computes a "
            "single correction target, not per-segment targets, for reference):"
        )
        for seg in comparison["target_segments"]:
            lines.append(line(f"{seg['hour']:02d}:00", seg["current"], seg["recommended_correction_target"]))
        lines.append("")

    if schedule_proposal and any((schedule_proposal.get(k) or {}).get("segments") for k in SCHEDULE_SETTING_LABELS):
        lines.append("-- NEW TIME SEGMENTS (up to 8 per setting, boundaries discovered from the data) --")
        lines.append("")
        for key, label in SCHEDULE_SETTING_LABELS.items():
            setting = schedule_proposal.get(key) or {}
            segments = setting.get("segments") or []
            if not segments:
                continue
            lines.append(f"{label}:")
            if setting.get("note"):
                lines.append(f"  {setting['note']}")
            for seg in segments:
                lines.append(
                    f"  [{seg['time_block']}] current weighted baseline: {seg['current_weighted_baseline']}"
                    f"  ->  proposed: {seg['proposed_value']}  ({seg['confidence']})"
                )
            lines.append("")

    return lines


EVIDENCE_DISPLAY_LIMIT = 8  # cap per-finding evidence rows shown in text output


def _format_evidence_row(setting: str, row: dict) -> str:
    """One concrete evidence line (date, times, BG before/after) for a finding."""
    if setting == "Basal":
        return (
            f"      {row['date']}  {row['time_start']}->{row['time_end']}  "
            f"BG {row['bg_start']:.0f}->{row['bg_end']:.0f} mg/dL  "
            f"({row['slope_mgdl_per_hr']:+.1f} mg/dL/hr)"
        )
    if setting == "Insulin-to-Carb Ratio (ICR)":
        return (
            f"      {row['date']} {row['time']}  {row['carbs']:.0f}g carbs  "
            f"BG {row['bg_before']:.0f} before -> {row['bg_after']:.0f} mg/dL after"
        )
    if setting == "Correction Factor / Sensitivity (ISF)":
        return (
            f"      {row['date']} {row['time']}  {row['correction_dose']:.2f}u correction  "
            f"BG {row['bg_before']:.0f} before -> {row['bg_after']:.0f} mg/dL after"
        )
    if setting == "Target Glucose (BGT)":
        return f"      {row['date']}  below range {row['below_pct']:.0f}%, above range {row['above_pct']:.0f}%"
    return f"      {row}"


SCHEDULE_SETTING_LABELS = {
    "carb_ratio": "INSULIN-TO-CARB RATIO (ICR)",
    "isf": "CORRECTION FACTOR / SENSITIVITY (ISF)",
    "target": "TARGET GLUCOSE (BGT)",
}


def build_findings_report(findings: list) -> list:
    """Format the baseline-relative "Quick Proposal Template" findings as
    text lines: one block per setting+segment with the pattern observed,
    proposed change, confidence, concrete evidence (dates/times/BG
    before-after), and what to watch -- meant to be brought to an
    appointment, per the tuning guide this methodology follows.
    """
    if not findings:
        return []

    lines = [
        "=" * 60,
        "PROPOSAL REPORT (bring this to your appointment)",
        "=" * 60,
        "",
        TUNING_PROCESS_NOTE,
        "",
    ]

    current_setting = None
    for finding in findings:
        if finding["setting"] != current_setting:
            current_setting = finding["setting"]
            lines.append(f"\n{current_setting.upper()}:")

        lines.append(f"  [{finding['time_block']}] current: {finding['current_value']}")
        lines.append(f"    pattern observed: {finding['pattern_observed']}")
        if finding["proposed_direction"] == "no change":
            lines.append(f"    proposed: no change ({finding['confidence']})")
        else:
            magnitude = f" ({finding['magnitude_pct']:.0f}%)" if finding.get("magnitude_pct") else ""
            lines.append(
                f"    proposed: {finding['proposed_direction']} to {finding['proposed_value']}"
                f"{magnitude} -- {finding['confidence']}"
            )
            if finding.get("what_to_watch"):
                lines.append(f"    what to watch: {finding['what_to_watch']}")

        evidence = finding.get("evidence") or []
        if evidence:
            lines.append("    evidence:")
            for row in evidence[:EVIDENCE_DISPLAY_LIMIT]:
                lines.append(_format_evidence_row(finding["setting"], row))
            if len(evidence) > EVIDENCE_DISPLAY_LIMIT:
                lines.append(f"      ... and {len(evidence) - EVIDENCE_DISPLAY_LIMIT} more (full list in JSON output)")

        lines.append("")

    return lines


def format_disclaimer_block(data: dict) -> str:
    """Format the disclaimer and any data-quality warnings for text output."""
    lines = ["!" * 60, "DISCLAIMER", "!" * 60, DISCLAIMER]

    recs = data.get("recommendations", data)
    warnings = recs.get("warnings") if isinstance(recs, dict) else None
    if warnings:
        lines.append("")
        lines.append("DATA QUALITY WARNINGS:")
        for warning in warnings:
            lines.append(f"  - {warning}")

    lines.append("!" * 60)
    return "\n".join(lines)


def format_output(data: dict) -> str:
    """Format output as human-readable text."""
    lines = []
    
    if "recommendations" in data:
        # Full report
        lines.append("=" * 60)
        lines.append("GLUCOLENS - OMNIPOD RECOMMENDATIONS REPORT")
        lines.append("=" * 60)
        
        if "data_summary" in data:
            summary = data["data_summary"]
            lines.append("\nDATA SUMMARY:")
            if summary.get("patient_name"):
                lines.append(f"  Patient: {summary['patient_name']}")
            lines.append(f"  Total readings: {summary.get('total_readings', 'N/A')}")
            lines.append(f"  Total meals: {summary.get('total_meals', 'N/A')}")
            lines.append(f"  Total insulin events: {summary.get('total_insulin_events', 'N/A')}")
            date_range = summary.get("date_range") or {}
            if date_range.get("start") and date_range.get("end"):
                lines.append(f"  Date range: {date_range['start']} to {date_range['end']}")
            if summary.get("duration_days") is not None:
                lines.append(f"  Duration: {summary['duration_days']} day(s)")
        
        if "glucose_statistics" in data:
            lines.append("\nGLUCOSE STATISTICS:")
            stats = data["glucose_statistics"]
            lines.append(f"  Mean: {stats.get('mean', 'N/A'):.1f} mg/dL")
            lines.append(f"  Std Dev: {stats.get('std_dev', 'N/A'):.1f} mg/dL")
            lines.append(f"  Range: {stats.get('min', 'N/A'):.0f} - {stats.get('max', 'N/A'):.0f} mg/dL")
        
        if "time_in_range" in data:
            lines.append("\nTIME IN RANGE:")
            tir = data["time_in_range"]
            lines.append(f"  In Range (70-180): {tir.get('time_in_range_percent', 0):.1f}%")
            lines.append(f"  Below Range: {tir.get('time_below_percent', 0):.1f}%")
            lines.append(f"  Above Range: {tir.get('time_above_percent', 0):.1f}%")
        
        if "recommendations" in data:
            lines.append("\n" + "=" * 60)
            lines.append("OMNIPOD RECOMMENDATIONS:")
            lines.append("=" * 60)
            recs = data["recommendations"]
            
            if "basal_profile" in recs:
                lines.append("\nBASAL RATE PROFILE:")
                for hour, rate in sorted(recs["basal_profile"]["rates"].items()):
                    lines.append(f"  {hour:02d}:00 - {rate:.2f} units/hour")
            
            if "insulin_sensitivity_factor" in recs:
                lines.append("\nINSULIN SENSITIVITY FACTOR:")
                isf = recs["insulin_sensitivity_factor"]
                sample_hours = [0, 6, 12, 18]
                for hour in sample_hours:
                    factor = isf["factors"].get(hour, "N/A")
                    lines.append(f"  {hour:02d}:00 - 1:{factor} mg/dL per unit")
            
            if "carb_ratio" in recs:
                lines.append("\nCARB-TO-INSULIN RATIO:")
                carb_ratio = recs["carb_ratio"]
                sample_hours = [7, 12, 18, 22]
                for hour in sample_hours:
                    ratio = carb_ratio["ratios"].get(hour, "N/A")
                    lines.append(f"  {hour:02d}:00 - 1 unit per {ratio}g carbs")
            
            lines.append("\nTARGET SETTINGS:")
            lines.append(f"  Target range: {recs.get('target_glucose_min', 70):.0f} - "
                        f"{recs.get('target_glucose_max', 180):.0f} mg/dL")
            lines.append(f"  Correction target: {recs.get('correction_target', 120):.0f} mg/dL")
            lines.append(f"  Max bolus: {recs.get('max_bolus', 30):.1f} units")
            lines.append(f"  Max basal: {recs.get('max_basal', 3):.2f} units/hour")
    else:
        # Simple recommendations
        if "basal_profile" in data:
            lines.append("BASAL RATES:")
            for hour, rate in sorted(data["basal_profile"]["rates"].items()):
                lines.append(f"  {hour:02d}:00 - {rate:.2f} units/hour")
    
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
