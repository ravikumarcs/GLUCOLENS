"""Shared user-facing text used by both the CLI and the web UI."""

DISCLAIMER = (
    "These recommendations are for EDUCATIONAL PURPOSES ONLY. Do NOT use them "
    "to adjust your Omnipod pump or any other insulin delivery device without "
    "professional medical supervision. Always consult your endocrinologist or "
    "diabetes care team before changing pump settings."
)

AUTOMATED_MODE_NOTE = (
    "If this pump runs in an automated hybrid closed-loop mode (e.g. Omnipod 5 "
    "Automated Mode), it adjusts basal delivery in real time toward the "
    "configured Target BG -- Max Basal, Target BG, ISF, and Carb Ratio matter "
    "far more to outcomes than the static basal schedule below, which the "
    "automated algorithm largely overrides."
)

TUNING_PROCESS_NOTE = (
    "Before acting on any finding below: change ONE setting at a time (never "
    "ICR and CF, or ICR and Target, in the same round -- if glucose improves "
    "or a new low shows up, you won't know which change caused it). Use small "
    "steps (10-20%, smaller still for pediatric dosing). Hold 3-5 days after "
    "any single change before pulling fresh data and re-checking. Don't act "
    "on a single outlier day -- these findings already require the same "
    "pattern on 3+ separate days/events before proposing anything. Sequence: "
    "Basal, then ICR, then CF, then Target -- fixing things out of order "
    "risks chasing a symptom of a basal problem instead of the basal problem "
    "itself."
)
