# How GlucoLens Estimates Each Setting (Plain-English Guide)

> **This document explains the math and logic behind every number GlucoLens
> produces.** It's written for a parent or caregiver, not a programmer — no
> code required to follow along. If you *do* want the code, every section
> below names the exact file and function it's describing.
>
> **This is not medical advice.** Nothing in this document, or produced by
> this tool, should be entered into a pump without your endocrinologist or
> diabetes care team reviewing it first. See [Disclaimer](#disclaimer) at
> the end.

---

## The big picture: two different modes

GlucoLens computes settings one of two ways, depending on what you give it:

| You provide... | Mode used | What it does |
|---|---|---|
| Just CGM/meal/insulin data | **Generic estimate** | Calculates settings from scratch using standard diabetes formulas (the same ones an endocrinologist uses as a starting point for a *new* patient), then nudges them slightly toward what your CGM data shows. |
| CGM data **plus your current pump settings** (uploaded as a PDF, a JSON file, or typed in manually) | **Personalized refinement** | Looks at *your current numbers* and asks: "does the data show evidence this specific number is wrong?" It only proposes a small change when it finds a repeated pattern — otherwise it leaves your current number untouched. |

**In practice, if you've uploaded your Glooko PDF or current settings, you're
using the second mode** — that's the one that produces the "Proposal for
Your Appointment" report. The rest of this document explains that mode in
detail, since it's the one that actually looks at *your* current numbers,
and calls out where the generic (first) mode works differently.

---

## A few terms, explained simply

- **Basal rate** — the small, constant trickle of insulin the pump delivers
  in the background, all day and night, whether or not you eat. It's what
  keeps blood sugar stable between meals and overnight.
- **ICR (Insulin-to-Carb Ratio)** — how many grams of carbs one unit of
  insulin covers at mealtime. Written like `1:15` (1 unit per 15g). A
  *smaller* number (like `1:8`) means *more* insulin per gram — a
  "stronger" ratio.
- **ISF / Correction Factor** — how much one unit of insulin lowers blood
  sugar when correcting a high. Written like `1:150` (1 unit drops glucose
  by ~150 mg/dL). A *smaller* number means a *more aggressive* correction.
- **Target glucose** — the number the pump's automatic corrections aim for.
- **TDD (Total Daily Dose)** — all the insulin someone uses in a day, basal
  plus meal boluses plus corrections, added up.
- **TIR (Time in Range)** — the percentage of the day glucose spent between
  70–180 mg/dL (the standard "in range" band).
- **Segment** — pump settings aren't usually one flat number all day; they're
  broken into time blocks ("segments"), e.g. a different ICR for breakfast
  vs. dinner. GlucoLens evaluates each segment on its own.
- **"Clean window"** — a stretch of time with no meal and no insulin bolus
  recently active, so any glucose movement can only be explained by the
  basal rate, not by food or a bolus still working.

---

## Before any setting is calculated: data quality checks

These run first, on every use, and apply to everything below:

- **Sensor-error filtering**: any CGM reading below 40 or above 400 mg/dL is
  thrown out before any calculation — these are essentially always sensor
  errors, not real blood sugar.
  *(`GlucoseAnalyzer.MIN_VALID_GLUCOSE` / `MAX_VALID_GLUCOSE`, `src/analysis.py`)*
- **Minimum data check**: if there's less than 3 days of data, GlucoLens
  still produces output, but adds a loud warning that everything is
  low-confidence. 14+ days is recommended for anything meaningful.
  *(`MIN_SUFFICIENT_DAYS`, `src/analysis.py`)*
- Every proposed change also comes with a **confidence note** telling you
  exactly how much evidence supported it (e.g. "supported (n=5)" or
  "insufficient evidence").

---

## The "Rule of Three" and "small steps" — used by every setting below

Before explaining each setting individually, it helps to understand the two
rules that govern *all* of the personalized-refinement proposals:

1. **Rule of Three**: a pattern has to show up on **at least 3 separate
   days or events** before GlucoLens will propose a change. One bad day (a
   birthday party, a sick day, a sensor glitch) is never enough on its own.
   If fewer than 3 qualifying instances are found, the current value is
   left exactly as-is, and the report says so explicitly.
2. **Small, fixed steps**: when a change *is* proposed, it's always a fixed
   **15% adjustment** to the *current* number (10% for the target glucose,
   which is measured in mg/dL rather than a ratio — see below) — never a
   number calculated from scratch, and never a bigger jump no matter how
   strong the pattern looks. This mirrors standard clinical practice of
   making small, single-variable changes and re-checking, rather than
   large jumps that are hard to attribute to any one cause.

Both rules exist so this tool proposes *directionally correct, cautious*
nudges — not confident-sounding numbers pulled from thin evidence.

---

## Basal Rate

**What it does:** the constant background insulin drip, usually several
different rates across the day (e.g., lower overnight, higher in the early
morning).

### Personalized refinement (you provided current settings)

For each of your current basal segments, GlucoLens looks only at **"clean
windows"** — stretches of at least 5 hours with no meal and no active bolus
insulin (overnight is the classic example, but any long gap between meals
counts too). Within those clean windows, it checks: is glucose *steadily*
drifting up or down (a straight-line trend), rather than just bouncing
around randomly?

- **Steady rise** → basal is probably **too low** for that time block →
  propose raising it.
- **Steady fall** → basal is probably **too high** → propose lowering it.
- Needs the same direction on **3+ separate clean windows** (Rule of Three)
  before proposing anything; a single night's drift isn't enough.
- When proposed, the change is **±15%** of your current rate.

*(`GlucoseAnalyzer.find_clean_windows` and `compute_basal_drift`,
`src/analysis.py`; `OmnipodRecommendationEngine._generate_basal_profile_from_baseline`,
`src/recommendation_engine.py`)*

**Why this one comes first:** basal is deliberately evaluated before ICR,
ISF, or target. If basal is wrong, it throws off the readings used to judge
everything else — a meal that looks like it needed "more insulin" might
really just be riding on top of a basal rate that was already too low. If a
basal issue is found, the report puts a loud warning at the top telling you
to address that first.

### Generic estimate (no current settings provided)

Without a baseline to adjust, GlucoLens instead estimates basal from
scratch: it takes your Total Daily Dose (TDD, see below), assumes roughly
half of it is basal (or uses your actual basal/bolus split if your data
distinguishes them), spreads that evenly across 24 hours, then applies a
generic time-of-day shape (lower at night, higher in the morning) and a
bounded nudge from your CGM data. If there's no dosing history at all, it
falls back to a generic default (0.5 units/hour).

---

## Insulin-to-Carb Ratio (ICR)

**What it does:** how many grams of carbs one unit of insulin covers at a
meal.

### Personalized refinement

For each of your current ICR segments (e.g., "breakfast: 1:8"), GlucoLens
looks at meals in that time window — but **only meals where blood sugar was
already in range (70–180 mg/dL) before eating**, since a meal that started
high or low can't tell you whether the ratio itself is right.

For each qualifying meal, it checks two windows after eating:

- **2 to 3 hours after eating**: any low reading (under 70)? → **crashed**,
  meaning the ratio is delivering **too much** insulin for the carbs
  → propose **weakening** it (raising the number, e.g. `1:10` → `1:11.5`).
- **Right around the 3-hour mark**: did glucose spike significantly above
  target (more than 50 mg/dL over 180) *and* is it still elevated at 3
  hours? → **spiked and stayed high**, meaning the ratio is delivering
  **too little** insulin → propose **strengthening** it (lowering the
  number, e.g. `1:10` → `1:8.5`).
- Otherwise → **on target**, no issue with this meal.

Needs **3+ meals** showing the same issue in that segment (Rule of Three)
before proposing anything. When proposed, it's a **15%** change to the
current number, always kept between 1 unit per 3g and 1 unit per 50g (a
sanity clamp against typos or wild swings).

*(`GlucoseAnalyzer.analyze_meal_response_for_icr`, `src/analysis.py`;
`OmnipodRecommendationEngine._generate_carb_ratio_from_baseline`,
`src/recommendation_engine.py`)*

**Worked example:** current ratio is `1:5.5`. Out of 16 qualifying
breakfast-window meals, 5 spiked and stayed high at 3 hours. 5 ≥ 3, so a
change is proposed: `5.5 × 0.85 = 4.675`, rounded to **4.7** → "strengthen
from 1:5.5 to 1:4.7 (15%)."

### Generic estimate

Without current settings, GlucoLens uses the standard **"500 rule"**:
`500 ÷ Total Daily Dose`. If you also have meal-response CGM data, it's
blended in as a small (±20%) adjustment on top — never the primary driver.
Without any dosing history at all, it falls back to a plain 1-unit-per-15g
default.

---

## Insulin Sensitivity Factor (ISF) / Correction Factor

**What it does:** how much one unit of insulin lowers a high blood sugar
when correcting (not eating).

### Personalized refinement

This one is the pickiest about its evidence. GlucoLens looks only at
**correction-only boluses** — a dose of insulin given with **no meal within
3 hours before or after it**, so the response can only be attributed to the
correction itself, not food. For each one, it checks glucose 3–4 hours
later:

- **Still elevated** (above 180) → correction wasn't strong enough → ISF is
  **too weak** → propose **lowering** the number (more aggressive
  correction).
- **Went low** (under 70) in that window → correction was too strong → ISF
  is **too strong** → propose **raising** the number (gentler correction).

Needs **3+ qualifying correction-only events** in that segment. This is
often the hardest evidence to gather — a truly isolated correction (no meal
anywhere nearby) doesn't happen often in everyday use, especially on an
automated closed-loop pump that's frequently making its own small
adjustments. **When there isn't enough of this kind of event, GlucoLens says
so explicitly rather than guessing** — and notes that the scarcity itself
is useful information to bring to your care team (it may mean an in-clinic
ISF test is more appropriate than a CGM-data read).

*(`GlucoseAnalyzer.analyze_correction_only_events`, `src/analysis.py`;
`OmnipodRecommendationEngine._generate_isf_from_baseline`,
`src/recommendation_engine.py`)*

### Generic estimate

Without current settings, GlucoLens uses the standard **"1800 rule"**:
`1800 ÷ Total Daily Dose`, with a small (±15%) time-of-day adjustment for
the dawn phenomenon (early morning insulin resistance) and overnight
sensitivity. Without dosing history, it falls back to picking a number
based on how high glucose currently runs at that hour — the least reliable
of all the fallbacks, and flagged as such.

---

## Target Glucose

**What it does:** the number an automated pump's corrections aim for
throughout the day (distinct from the 70–180 mg/dL "in range" band used for
TIR reporting).

### Personalized refinement

For each of your current target segments, GlucoLens looks at how many
**separate days** in that time window were dominated by lows vs. highs:

- **Lows-dominant on 3+ days** → the target is set too tight → propose
  **raising** it by 10 mg/dL (more buffer).
- **Highs-dominant on 3+ days** (and lows aren't the bigger problem) →
  there's room to tighten → propose **lowering** it by 10 mg/dL.

This one is checked **last**, on purpose — target interacts with both ICR
and ISF, so it's most meaningful once those have already been reviewed and
any changes have had time to settle.

*(`GlucoseAnalyzer.compute_daily_tir_by_hour_range`, `src/analysis.py`;
`OmnipodRecommendationEngine._analyze_target_segments`,
`src/recommendation_engine.py`)*

*Note: this per-segment analysis only appears in the "Proposal for Your
Appointment" report. The single "Correction Target" number shown elsewhere
in the output is computed completely differently and far more simply — see
below.*

### The single "Correction Target" number

Separately from the per-segment analysis above, GlucoLens also always
computes one flat overall correction target, shown in the main
recommendations output. This one is **mostly a fixed default, not really a
calculation**: it's 120 mg/dL unless your average glucose is already under
120, in which case it backs off to (average − 10) so it never suggests
correcting toward a number below where you're already running. It's then
kept safely above the low-glucose threshold no matter what. Treat this
particular number as the least personalized one GlucoLens produces.

*(`OmnipodRecommendationEngine._estimate_correction_target`,
`src/recommendation_engine.py`)*

---

## Max Bolus and Max Basal (safety ceilings)

These aren't "recommended settings" in the same sense as the others —
they're upper limits meant to catch mistakes (like an accidental extra
zero), not targets to aim for.

- **When you provided current settings**: GlucoLens leaves these exactly as
  they currently are. There's no methodology in this tool for judging
  whether a safety ceiling should change — that's a clinical decision, not
  a pattern to detect in CGM data.
- **When there's no baseline**: GlucoLens estimates them from your Total
  Daily Dose instead of using one-size-fits-all numbers — a single bolus
  rarely exceeds about 30% of TDD in normal use, and max basal is set to
  roughly 2.5× the highest hourly basal rate it computed. Both are capped
  at Omnipod's hardware limits either way. This matters because a flat,
  non-personalized "safe" ceiling (say, 30 units) is not actually safe for
  a small child on a low dose — it's just a big number.

*(`_estimate_max_bolus`, `_estimate_max_basal`, `src/recommendation_engine.py`)*

---

## Active Insulin Time

This one isn't calculated at all — it's a pass-through. GlucoLens uses
whatever value you tell it (from your uploaded settings) purely to define
"how long after a meal or bolus counts as insulin still being active" for
its own internal calculations (like deciding what counts as a "clean
window" for basal analysis). It never proposes changing this number itself
— it's a clinical/pharmacokinetic setting (how long the specific insulin
you use keeps working in the body), not something CGM data alone can tell
you.

---

## What GlucoLens does *not* do

Being explicit about the boundaries matters as much as explaining the
methodology:

- It does not know why any of your current numbers were originally set the
  way they are. A tightly-tuned segment (say, a strong morning ICR set on
  purpose for dawn-phenomenon insulin resistance) looks the same to this
  tool as an untuned default — it can only react to what the CGM data shows
  *now*.
- It never makes more than one proposed step per setting per run. If a
  pattern is very strong, the proposal is still capped at 15% (10 mg/dL for
  target) — bigger changes are expected to happen over multiple
  review-and-recheck cycles, not in one jump.
- It cannot verify accurate carb counting, correct pre-bolusing, exercise,
  illness, or other real-world factors that affect glucose response — the
  Rule of Three (requiring 3+ independent instances) is the main defense
  against these confounders, not a guarantee against them.
- It does not automatically apply anything to a pump. Every number is a
  suggestion, not an action.

---

## Disclaimer

**Every number this tool produces is for discussion with your
endocrinologist or diabetes care team — never for direct entry into a pump.**
This is especially true for pediatric dosing, where the margin for error is
smaller and the standard of care requires a clinician's judgment that this
tool cannot replace. GlucoLens looks for statistical patterns in CGM data;
it has no knowledge of the medical reasoning behind your current settings,
no ability to examine growth, activity, illness, or other clinical context,
and no accountability for outcomes. Treat every proposal here as a
starting point for a conversation, not a conclusion.
