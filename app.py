#!/usr/bin/env python
"""GlucoLens web UI: upload a Glooko export, view Omnipod recommendations.

Run locally with:
    streamlit run app.py

Everything runs on your own machine -- uploaded files are written to a
temporary directory only for the duration of loading, then discarded.
Nothing is sent to any external server.
"""

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from src.data_loader import GlookoDataLoader
from src.recommendation_engine import OmnipodRecommendationEngine
from src.comparison import compare_settings
from src.constants import DISCLAIMER, AUTOMATED_MODE_NOTE, TUNING_PROCESS_NOTE
from src.pdf_settings import parse_glooko_pdf


st.set_page_config(page_title="GlucoLens", page_icon="🩸", layout="wide")


def render_disclaimer():
    st.markdown(
        f"""
        <div style="background-color:#fee2e2;border:2px solid #dc2626;
                    border-radius:8px;padding:12px 16px;margin-bottom:16px;
                    color:#7f1d1d;">
        <strong>⚠️ Disclaimer:</strong> {DISCLAIMER}
        </div>
        """,
        unsafe_allow_html=True,
    )


def hourly_dataframe(values_by_hour: dict, column: str) -> pd.DataFrame:
    return pd.DataFrame(
        {column: [values_by_hour.get(h, values_by_hour.get(str(h))) for h in range(24)]},
        index=pd.Index(range(24), name="hour"),
    )


def segment_dataframe(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "hour" in df.columns:
        df.insert(0, "time", df["hour"].apply(lambda h: f"{h:02d}:00"))
        df = df.drop(columns="hour")
    return df


EVIDENCE_COLUMN_LABELS = {
    "Basal": {
        "date": "Date", "time_start": "Window start", "bg_start": "BG at start (mg/dL)",
        "time_end": "Window end", "bg_end": "BG at end (mg/dL)", "slope_mgdl_per_hr": "Slope (mg/dL/hr)",
    },
    "Insulin-to-Carb Ratio (ICR)": {
        "date": "Date", "time": "Meal time", "carbs": "Carbs (g)",
        "bg_before": "BG before (mg/dL)", "bg_after": "BG ~3h after (mg/dL)",
    },
    "Correction Factor / Sensitivity (ISF)": {
        "date": "Date", "time": "Correction time", "correction_dose": "Dose (U)",
        "bg_before": "BG before (mg/dL)", "bg_after": "BG 3-4h after (mg/dL)",
    },
    "Target Glucose (BGT)": {
        "date": "Date", "below_pct": "Below range (%)", "above_pct": "Above range (%)",
    },
}


def evidence_dataframe(setting: str, evidence: list) -> pd.DataFrame:
    df = pd.DataFrame(evidence)
    labels = EVIDENCE_COLUMN_LABELS.get(setting, {})
    return df.rename(columns=labels)


def render_results(results: dict):
    data = results["data"]
    recommendations = results["recommendations"]
    recommendation_dict = results["recommendation_dict"]
    stats = results["stats"]
    tir = results["tir"]
    current_settings = results["current_settings"]

    st.header("Data Summary")
    start, end = data.get_time_range()
    days = (end - start).days + 1 if start and end else 0
    cols = st.columns(4)
    cols[0].metric("Glucose readings", len(data.glucose_readings))
    cols[1].metric("Meals", len(data.meals))
    cols[2].metric("Insulin events", len(data.insulin_events))
    cols[3].metric("Days covered", days)

    st.header("Glucose Statistics")
    cols = st.columns(3)
    cols[0].metric("Mean glucose", f"{stats.get('mean', 0):.0f} mg/dL")
    cols[1].metric("Std Dev", f"{stats.get('std_dev', 0):.0f} mg/dL")
    cols[2].metric("Range", f"{stats.get('min', 0):.0f}-{stats.get('max', 0):.0f} mg/dL")

    cols = st.columns(3)
    cols[0].metric("Time in Range (70-180)", f"{tir.get('time_in_range_percent', 0):.1f}%")
    cols[1].metric("Time Below Range", f"{tir.get('time_below_percent', 0):.1f}%")
    cols[2].metric("Time Above Range", f"{tir.get('time_above_percent', 0):.1f}%")

    if recommendations.warnings:
        st.header("Data Quality Warnings")
        for warning in recommendations.warnings:
            st.warning(warning)

    st.header("Recommended Settings")
    cols = st.columns(4)
    cols[0].metric(
        "Target range",
        f"{recommendations.target_glucose_min:.0f}-{recommendations.target_glucose_max:.0f} mg/dL",
    )
    cols[1].metric("Correction target", f"{recommendations.correction_target:.0f} mg/dL")
    cols[2].metric("Max bolus", f"{recommendations.max_bolus:.1f} U")
    cols[3].metric("Max basal", f"{recommendations.max_basal:.2f} U/hr")

    st.subheader("Basal Rate Profile")
    st.line_chart(hourly_dataframe(recommendations.basal_profile.rates, "units/hr"))

    st.subheader("Insulin Sensitivity Factor")
    st.line_chart(hourly_dataframe(recommendations.insulin_sensitivity_factor.factors, "mg/dL per unit"))

    st.subheader("Carb Ratio")
    st.line_chart(hourly_dataframe(recommendations.carb_ratio.ratios, "g per unit"))

    findings = results.get("findings") or []
    if findings:
        st.header("Proposal for Your Appointment")
        st.info(TUNING_PROCESS_NOTE)

        setting_order = [
            "Basal",
            "Insulin-to-Carb Ratio (ICR)",
            "Correction Factor / Sensitivity (ISF)",
            "Target Glucose (BGT)",
        ]
        findings_by_setting: dict = {}
        for finding in findings:
            findings_by_setting.setdefault(finding["setting"], []).append(finding)

        for setting in setting_order:
            rows = findings_by_setting.get(setting)
            if not rows:
                continue
            st.subheader(setting)
            for finding in rows:
                has_change = finding["proposed_direction"] != "no change"
                label = f"{finding['time_block']} -- current: {finding['current_value']}"
                if has_change:
                    label += f" -> proposed: {finding['proposed_value']} ({finding['proposed_direction']})"
                else:
                    label += " -- no change proposed"
                with st.expander(label, expanded=has_change):
                    st.write(f"**Pattern observed:** {finding['pattern_observed']}")
                    st.write(f"**Confidence:** {finding['confidence']}")
                    if finding.get("what_to_watch"):
                        st.write(f"**What to watch:** {finding['what_to_watch']}")
                    evidence = finding.get("evidence") or []
                    if evidence:
                        st.write("**Evidence:**")
                        st.dataframe(
                            evidence_dataframe(setting, evidence),
                            hide_index=True,
                            use_container_width=True,
                        )

    schedule_proposal = results.get("schedule_proposal") or {}
    schedule_labels = {
        "carb_ratio": "Insulin-to-Carb Ratio (ICR)",
        "isf": "Correction Factor / Sensitivity (ISF)",
        "target": "Target Glucose (BGT)",
    }
    has_schedule_proposal = any(schedule_proposal.get(k, {}).get("segments") for k in schedule_labels)

    if current_settings:
        st.header("Current vs Recommended")
        st.info(AUTOMATED_MODE_NOTE)

        comparison = compare_settings(current_settings, recommendation_dict)

        st.subheader("Key Settings")
        st.dataframe(pd.DataFrame(comparison["scalars"]), hide_index=True, use_container_width=True)

        st.subheader("Same Time Segments (today's boundaries, adjusted values)")
        for key, title in [
            ("basal_segments", "Basal Rate (units/hr)"),
            ("isf_segments", "Insulin Sensitivity Factor (1:X mg/dL per unit)"),
            ("carb_ratio_segments", "Carb Ratio (g per unit)"),
        ]:
            if comparison[key]:
                st.markdown(f"**{title}**")
                st.dataframe(segment_dataframe(comparison[key]), hide_index=True, use_container_width=True)

        if comparison["target_segments"]:
            st.markdown("**Target BG (mg/dL)**")
            st.caption(
                "This tool computes a single overall correction target, not "
                "per-segment targets -- shown here for reference against each "
                "current segment."
            )
            st.dataframe(segment_dataframe(comparison["target_segments"]), hide_index=True, use_container_width=True)

        if has_schedule_proposal:
            st.subheader("New Time Segments (boundaries discovered from the data, up to 8 per setting)")
            st.caption(
                "A different question than the segments above (\"should today's "
                "numbers change\" vs. \"is today's schedule shape even right\"). "
                "Same caution applies: one variable at a time, small steps, hold "
                "and re-check."
            )
            for key, label in schedule_labels.items():
                setting = schedule_proposal.get(key) or {}
                segments = setting.get("segments") or []
                if not segments:
                    continue
                st.markdown(f"**{label}**")
                if setting.get("note"):
                    st.info(setting["note"])
                df = pd.DataFrame(segments)[
                    ["time_block", "current_weighted_baseline", "proposed_value", "confidence"]
                ].rename(columns={
                    "time_block": "Time block",
                    "current_weighted_baseline": "Current weighted baseline",
                    "proposed_value": "Proposed value",
                    "confidence": "Confidence",
                })
                st.dataframe(df, hide_index=True, use_container_width=True)

    st.header("Download")
    report_with_disclaimer = {"disclaimer": DISCLAIMER, **recommendation_dict}
    st.download_button(
        "Download recommendations (JSON)",
        data=json.dumps(report_with_disclaimer, indent=2, default=str),
        file_name="glucolens_recommendations.json",
        mime="application/json",
    )


def main():
    st.title("🩸 GlucoLens")
    st.caption("Glooko diabetes data → Omnipod pump setting recommendations")
    render_disclaimer()

    st.header("1. Upload Glooko Export")
    uploaded_file = st.file_uploader(
        "Upload a Glooko export (.zip), or a single CSV/JSON export",
        type=["zip", "csv", "json"],
    )

    st.header("2. Current Pump Settings (optional, for comparison)")
    settings_source = st.radio(
        "How do you want to provide your currently-configured pump settings?",
        ["None", "Upload Glooko PDF report", "Upload settings JSON", "Enter manually"],
        horizontal=True,
    )

    current_settings = None

    if settings_source == "Upload Glooko PDF report":
        pdf_file = st.file_uploader(
            "Upload the Glooko PDF report (settings are read from its 'Devices' page)",
            type=["pdf"],
            key="settings_pdf_upload",
        )
        if pdf_file is not None:
            try:
                current_settings = parse_glooko_pdf(pdf_file)
            except Exception as e:
                st.error(f"Could not parse settings from this PDF: {e}")
                current_settings = None

            if current_settings is not None:
                if current_settings:
                    st.success("Parsed settings from PDF -- review before trusting them:")
                    st.json(current_settings)
                    st.caption(
                        "PDF text extraction is best-effort and can miss fields if Glooko "
                        "changes their report layout. Double-check these numbers against the "
                        "PDF itself, especially before using --compare results for anything."
                    )
                else:
                    st.warning(
                        "Couldn't find a recognizable pump settings section in this PDF. "
                        "Try 'Upload settings JSON' or 'Enter manually' instead."
                    )
                    current_settings = None

    elif settings_source == "Upload settings JSON":
        settings_file = st.file_uploader(
            "Upload current settings JSON (see data/sample_current_settings.json for the schema)",
            type=["json"],
            key="settings_upload",
        )
        if settings_file is not None:
            try:
                current_settings = json.load(settings_file)
            except json.JSONDecodeError as e:
                st.error(f"Could not parse current settings JSON: {e}")

    elif settings_source == "Enter manually":
        c1, c2, c3 = st.columns(3)
        max_basal = c1.number_input("Max Basal (units/hr)", min_value=0.0, value=0.0, step=0.05)
        max_bolus = c2.number_input("Max Bolus (units)", min_value=0.0, value=0.0, step=0.5)
        ait = c3.number_input("Active Insulin Time (hours)", min_value=0.0, value=0.0, step=0.5)

        c4, c5, c6, c7 = st.columns(4)
        basal_rate = c4.number_input("Basal rate, flat (units/hr)", min_value=0.0, value=0.0, step=0.05)
        isf_val = c5.number_input("ISF, flat (mg/dL per unit)", min_value=0.0, value=0.0, step=5.0)
        cr_val = c6.number_input("Carb ratio, flat (g per unit)", min_value=0.0, value=0.0, step=1.0)
        target_val = c7.number_input("Target BG, flat (mg/dL)", min_value=0.0, value=0.0, step=5.0)

        current_settings = {"active_insulin_time": ait or 4.0}
        if max_basal:
            current_settings["max_basal"] = max_basal
        if max_bolus:
            current_settings["max_bolus"] = max_bolus
        if basal_rate:
            current_settings["basal_segments"] = [{"start_hour": 0, "rate": basal_rate}]
        if isf_val:
            current_settings["isf_segments"] = [{"start_hour": 0, "value": isf_val}]
        if cr_val:
            current_settings["carb_ratio_segments"] = [{"start_hour": 0, "value": cr_val}]
        if target_val:
            current_settings["target_segments"] = [{"start_hour": 0, "target": target_val}]

    st.header("3. Run Analysis")
    run_clicked = st.button("Run Analysis", type="primary", disabled=uploaded_file is None)

    if run_clicked and uploaded_file is not None:
        try:
            with st.spinner("Loading data and analyzing..."):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir) / uploaded_file.name
                    tmp_path.write_bytes(uploaded_file.getvalue())
                    data = GlookoDataLoader.load(tmp_path)
                    # tmp_path (and any files extracted from it) are removed
                    # as soon as this block exits -- nothing persists on disk.

                active_insulin_time = (current_settings or {}).get("active_insulin_time", 4.0)
                engine = OmnipodRecommendationEngine(
                    data, active_insulin_time=active_insulin_time, current_settings=current_settings
                )
                recommendations = engine.generate_recommendations()

            st.session_state["results"] = {
                "data": data,
                "recommendations": recommendations,
                "recommendation_dict": recommendations.to_dict(),
                "stats": engine.analyzer.get_statistics(),
                "tir": engine.analyzer.get_time_in_range(),
                "current_settings": current_settings,
                "findings": engine.generate_findings_report(),
                "schedule_proposal": engine.generate_schedule_proposal(),
            }
        except Exception as e:
            st.error(f"Failed to process file: {e}")
            st.session_state.pop("results", None)

    if "results" in st.session_state:
        render_results(st.session_state["results"])


if __name__ == "__main__":
    main()
