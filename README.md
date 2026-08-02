# GlucoLens - Diabetes Data Analysis & Omnipod Recommendations

A Python-based software system that analyzes Glooko diabetes data and generates personalized Omnipod insulin pump setting recommendations.

## Features

- **Glooko Data Import**: Load glucose readings, meals, and insulin events from CSV or JSON exports
- **Glucose Analysis**:
  - Statistical metrics (mean, median, standard deviation)
  - Time in range calculations
  - Glucose variability analysis
  - Hourly glucose patterns
  - Low glucose event detection
  - Meal response pattern analysis

- **Omnipod Recommendations**:
  - Personalized basal rate profiles
  - Insulin sensitivity factors (ISF)
  - Carb-to-insulin ratios
  - Target glucose ranges
  - Maximum bolus and basal rates

- **Reporting**: Comprehensive analysis reports with visualizations and recommendations

## Installation

### Prerequisites
- Python 3.9+
- pip

### Setup

```bash
# Clone or navigate to the project directory
cd glucolens

# Install dependencies
pip install -r requirements.txt

# Optional: Install in development mode
pip install -e .
```

## Usage

### Command Line Interface

```bash
# Generate recommendations from Glooko data
python -m src.cli data/sample_glooko.json

# Save recommendations to file
python -m src.cli data/sample_glooko.json -o recommendations.json

# Generate detailed report
python -m src.cli data/sample_glooko.json -r

# Output as JSON
python -m src.cli data/sample_glooko.json -f json

# Compare against your current pump settings (see data/sample_current_settings.json
# for the schema) and get a personalized "Proposal for Your Appointment" report
python -m src.cli data/sample_glooko.json --compare data/sample_current_settings.json -r
```

### Web UI

A local Streamlit app supports uploading a Glooko export directly (a `.zip`
export, or a single CSV/JSON), and your current pump settings as a PDF
(parsed automatically from Glooko's "Devices" page), a JSON file, or manual
entry -- with charts, a data-quality summary, and the same proposal report
as the CLI.

```bash
streamlit run app.py
# opens at http://localhost:8501
```

Everything runs locally; uploaded files are processed in a temporary
location and never leave your machine.

### Python API

```python
from src.data_loader import GlookoDataLoader
from src.recommendation_engine import OmnipodRecommendationEngine

# Load data
loader = GlookoDataLoader()
data = loader.load('path/to/glooko_export.csv')

# Generate recommendations
engine = OmnipodRecommendationEngine(data)
recommendations = engine.generate_recommendations()

# Get summary report
report = engine.generate_summary_report()
```

## Data Format

### Supported Formats

#### CSV Export
Required columns:
- `timestamp`: Date/time of reading
- `glucose_value` or `Glucose Value`: Glucose value in mg/dL
- `carbs` or `Carbohydrates`: Carbohydrate grams (for meals)
- `insulin_amount` or `Insulin`: Insulin units (for injections)

#### JSON Export
```json
{
  "glucose_readings": [
    {
      "timestamp": "2024-01-15 08:00:00",
      "value": 120,
      "unit": "mg/dL",
      "source": "cgm"
    }
  ],
  "meals": [
    {
      "timestamp": "2024-01-15 08:00:00",
      "carbs": 45,
      "meal_type": "breakfast",
      "notes": "Optional notes"
    }
  ],
  "insulin_events": [
    {
      "timestamp": "2024-01-15 08:05:00",
      "amount": 4.0,
      "event_type": "bolus"
    }
  ]
}
```

## Output

### Recommendations Include

1. **Basal Profile**: Hourly insulin delivery rates (24 profiles)
2. **Insulin Sensitivity Factor (ISF)**: Correction factors by hour
3. **Carb Ratio**: Grams of carbs per insulin unit by hour
4. **Target Settings**: Glucose range targets and correction targets
5. **Safety Limits**: Maximum bolus and basal rates

### Sample Output

```
BASAL RATE PROFILE:
  00:00 - 0.50 units/hour
  06:00 - 0.55 units/hour
  12:00 - 0.60 units/hour
  18:00 - 0.58 units/hour

INSULIN SENSITIVITY FACTOR:
  06:00 - 1:85 mg/dL per unit
  12:00 - 1:100 mg/dL per unit
  18:00 - 1:95 mg/dL per unit
  22:00 - 1:110 mg/dL per unit

CARB-TO-INSULIN RATIO:
  07:00 - 1 unit per 12.7g carbs
  12:00 - 1 unit per 15.0g carbs
  18:00 - 1 unit per 16.5g carbs
  22:00 - 1 unit per 16.5g carbs
```

## Analysis Metrics

The engine calculates:

- **Time In Range (TIR)**: Percentage of readings within 70-180 mg/dL
- **Glucose Variability**: Coefficient of variation and rate of change
- **Meal Response**: Peak glucose, time to peak, glucose rise after meals
- **Low Glucose Events**: Frequency and duration of hypoglycemic episodes
- **Basal Requirements**: Estimated hourly insulin needs based on patterns

## Testing

Run tests:
```bash
python -m pytest tests/
# or
python -m unittest discover tests/
```

## Project Structure

```
glucolens/
├── src/
│   ├── __init__.py
│   ├── models.py               # Data models
│   ├── data_loader.py          # Glooko data import (single-file and real multi-file exports)
│   ├── analysis.py             # Glucose analysis engine (stats, patterns, evidence-gathering)
│   ├── recommendation_engine.py # Omnipod settings recommendations
│   ├── comparison.py           # Structured current-vs-recommended comparison
│   ├── pdf_settings.py         # Parses current settings from a Glooko PDF report
│   ├── segments.py             # Time-segment helpers
│   ├── constants.py            # Shared disclaimer/process-note text
│   └── cli.py                  # Command-line interface
├── app.py                      # Streamlit web UI
├── tests/                      # Unit tests, one file per src module
├── data/
│   ├── sample_glucose.csv      # Sample glucose data
│   ├── sample_meals.csv        # Sample meal data
│   ├── sample_insulin.csv      # Sample insulin data
│   ├── sample_glooko.json      # Sample JSON export
│   └── sample_current_settings.json  # Schema example for --compare / PDF-free comparison
├── docs/
│   ├── HOW_SETTINGS_ARE_ESTIMATED.md  # Plain-English methodology explanation
│   ├── API.md
│   └── GETTING_STARTED.md
├── .streamlit/config.toml      # Local-only binding, telemetry disabled
├── requirements.txt            # Python dependencies
├── setup.py                    # Package setup
└── .gitignore                  # Git ignore rules
```

## Limitations & Disclaimer

This software is for educational and informational purposes only. 

**⚠️ IMPORTANT DISCLAIMER:**
- These recommendations should NOT be used for actual insulin pump adjustments without professional medical review
- Always consult with an endocrinologist or diabetes care team before changing pump settings
- Diabetes management requires professional oversight and individualized care
- This tool is designed to assist in analysis, not replace medical professionals

## Algorithm Details

GlucoLens computes settings one of two ways:

- **No current settings provided**: a generic estimate from scratch, using
  standard clinical rules of thumb (the "1800 rule" for ISF, "500 rule" for
  carb ratio, both based on Total Daily Dose), lightly adjusted by CGM
  patterns.
- **Current settings provided** (via `--compare`, a Glooko PDF upload, or
  manual entry in the web UI): a personalized, evidence-gated refinement —
  each current segment is only nudged (a fixed, small step) when a pattern
  repeats across at least 3 independent days/events ("Rule of Three");
  otherwise it's left unchanged and flagged low-confidence. This mode also
  produces a "Proposal for Your Appointment" report with the evidence behind
  each suggestion.

**For a full, plain-English explanation of exactly how every setting (basal,
ISF, ICR, target, max bolus/basal) is calculated in both modes — including
the specific thresholds and worked examples — see
[docs/HOW_SETTINGS_ARE_ESTIMATED.md](docs/HOW_SETTINGS_ARE_ESTIMATED.md).**

## Future Enhancements

- Machine learning-based pattern recognition
- Integration with Omnipod API
- Multi-day and weekly trend analysis
- Predictive modeling for glucose trends
- PDF report generation (output, not just input)

## Contributing

Contributions welcome! Please follow PEP 8 and add tests for new features.

## License

MIT License - See LICENSE file for details

## Support

For issues or questions, please open an issue on the project repository.
