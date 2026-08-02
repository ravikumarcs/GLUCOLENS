<!-- Use this file to provide workspace-specific custom instructions to Copilot. -->

# GlucoLens Project - Development Notes

## Project Overview
GlucoLens is a Python application that analyzes Glooko diabetes data and generates personalized Omnipod insulin pump setting recommendations, with both a CLI and a local Streamlit web UI.

## Architecture

### Core Modules
1. **models.py** - Data structures for diabetes metrics
2. **data_loader.py** - Parse Glooko exports (single-file CSV/JSON, and real multi-file `.zip` exports)
3. **analysis.py** - Glucose pattern analysis: statistics, TIR, clean-window drift detection, meal-response and correction-only-event classification
4. **recommendation_engine.py** - Generates pump settings two ways: a TDD-based population-rule estimate (no baseline), or a baseline-relative, evidence-gated refinement of currently-configured settings (Rule of Three, bounded step size)
5. **comparison.py** - Structured current-vs-recommended comparison
6. **pdf_settings.py** - Best-effort parser for current settings from a Glooko PDF report
7. **segments.py** - Time-segment helpers
8. **constants.py** - Shared disclaimer/process-note text
9. **cli.py** - Command-line interface
10. **app.py** (project root) - Streamlit web UI

### Key Features
- Glucose statistics, time-in-range, and variability analysis
- Meal-response and correction-only-event pattern detection
- Evidence-gated basal/ISF/carb-ratio/target proposals, each requiring a repeated pattern (>=3 instances) before suggesting a change
- A "Proposal for Your Appointment" report (setting, time block, pattern observed, proposed change, confidence, what to watch)
- Web UI with file upload (Glooko export .zip/CSV/JSON, current settings via PDF/JSON/manual entry)

## Testing
```bash
python -m unittest discover -s tests -v
```

## Usage Examples

### CLI
```bash
python -m src.cli data/sample_glooko.json -r
python -m src.cli data/sample_glooko.json --compare data/sample_current_settings.json -r
```

### Web UI
```bash
streamlit run app.py
```

### Python API
```python
from src.data_loader import GlookoDataLoader
from src.recommendation_engine import OmnipodRecommendationEngine

data = GlookoDataLoader().load("file.json")
engine = OmnipodRecommendationEngine(data)
report = engine.generate_summary_report()
```

## Python Environment
- **Version**: 3.9+
- **Dependencies**: see `requirements.txt` (pandas, numpy, scipy, pydantic, python-dateutil, streamlit, pypdf)

## Important Notes
- All data processing is local -- no cloud/internet required, and the Streamlit server binds to localhost only (see `.streamlit/config.toml`)
- Educational purposes only -- requires medical consultation before acting on anything
- Every proposed setting change is bounded to a small step and gated on repeated evidence (Rule of Three) -- see `docs/HOW_SETTINGS_ARE_ESTIMATED.md` for the full methodology in plain English
- Works best with 2+ weeks of continuous glucose data

## Known Limitations
- Requires minimum data to generate reliable recommendations
- Does not account for exercise, stress, or illness
- Cannot verify accurate carb counting or pre-bolusing
- Limited to Glooko data format

## Documentation
- **README.md** - Project overview
- **docs/GETTING_STARTED.md** - User guide
- **docs/API.md** - Technical API reference
- **docs/HOW_SETTINGS_ARE_ESTIMATED.md** - Plain-English methodology for every setting
- **example_usage.py** - Working code examples

## Maintenance
- Code: PEP 8 compliant
- Tests: unit tests per module, no known failures
- No external services required
