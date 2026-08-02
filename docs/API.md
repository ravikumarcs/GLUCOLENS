# GlucoLens - API Documentation

## Overview

GlucoLens is a Python library for analyzing Glooko diabetes data and generating personalized Omnipod pump setting recommendations. This documentation covers the programmatic API.

## Installation

```python
# Install from the project directory
pip install -e /path/to/glucolens
```

## Core Modules

### 1. Models (`src/models.py`)

Data structures for diabetes management:

#### GlucoseReading
Represents a single glucose measurement:

```python
from src.models import GlucoseReading, GlucoseUnit
from datetime import datetime

reading = GlucoseReading(
    timestamp=datetime.now(),
    value=125.0,
    unit=GlucoseUnit.MG_DL,
    source="cgm"  # 'cgm' or 'meter'
)

# Convert to mmol/L
mmol = reading.to_mmol_l()
```

#### MealEvent
Records carbohydrate intake:

```python
from src.models import MealEvent, MealType

meal = MealEvent(
    timestamp=datetime.now(),
    carbs=45.0,
    meal_type=MealType.BREAKFAST,
    notes="Oatmeal with fruit"
)
```

#### InsulinEvent
Tracks insulin administration:

```python
from src.models import InsulinEvent

bolus = InsulinEvent(
    timestamp=datetime.now(),
    amount=4.5,
    event_type="bolus"
)
```

#### GloocolData
Container for all diabetes data:

```python
from src.models import GloocolData

data = GloocolData()
data.glucose_readings.append(reading)
data.meals.append(meal)
data.insulin_events.append(bolus)

# Get readings in a time range
readings = data.get_readings_in_range(start_time, end_time)

# Get data time range
start, end = data.get_time_range()
```

### 2. Data Loader (`src/data_loader.py`)

Load Glooko exports:

```python
from src.data_loader import GlookoDataLoader

loader = GlookoDataLoader()

# Auto-detect format (CSV or JSON)
data = loader.load("glooko_export.json")
data = loader.load("glooko_export.csv")

# Specific formats
data = loader.load_csv("glucoses.csv")
data = loader.load_json("glooko_data.json")
```

#### Supported CSV Columns
- `timestamp` or `time`: Date/time of reading
- `glucose_value` or `Glucose Value`: Glucose in mg/dL
- `carbs` or `Carbohydrates`: Grams of carbs
- `insulin_amount` or `Insulin`: Units of insulin
- `source`: Data source (cgm, meter, etc.)

#### Supported JSON Structure
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

### 3. Analysis Engine (`src/analysis.py`)

Analyze glucose patterns:

```python
from src.analysis import GlucoseAnalyzer

analyzer = GlucoseAnalyzer(data)

# Basic statistics
stats = analyzer.get_statistics()
# Returns: mean, median, std_dev, min, max, q25, q75

# Time in range
tir = analyzer.get_time_in_range(target_min=70, target_max=180)
# Returns: time_in_range_percent, time_below_percent, time_above_percent

# Hourly averages
hourly = analyzer.get_hourly_averages()
# Returns: {0: 110.5, 1: 105.3, ...}

# Variability metrics
variability = analyzer.get_glucose_variability()
# Returns: avg_rate_of_change, max_rate_of_change, std_dev_rate_of_change

# Meal response patterns
patterns = analyzer.detect_meal_response_pattern(window_hours=3.0)
# Returns: [{meal_time, carbs, pre_meal_glucose, peak_glucose, ...}, ...]

# Low glucose events
lows = analyzer.detect_low_glucose_events(threshold=70.0)
# Returns: [(start_time, end_time), ...]

# Basal requirements by hour
basals = analyzer.get_basal_requirements_by_hour()
# Returns: {0: 0.5, 1: 0.45, ...}
```

### 4. Recommendation Engine (`src/recommendation_engine.py`)

Generate pump settings:

```python
from src.recommendation_engine import OmnipodRecommendationEngine

engine = OmnipodRecommendationEngine(data)

# Generate recommendations
recommendations = engine.generate_recommendations()
# Returns: OmnipodSettings object

# Access settings
print(recommendations.basal_profile.rates)  # Dict of hourly rates
print(recommendations.insulin_sensitivity_factor.factors)  # Dict of hourly ISF
print(recommendations.carb_ratio.ratios)  # Dict of hourly C:I ratios

# Get complete report
report = engine.generate_summary_report()
# Returns: Dict with data_summary, glucose_statistics, time_in_range, etc.
```

### 5. Omnipod Settings (`src/models.py`)

Recommendation output:

```python
from src.models import OmnipodSettings

settings = recommendations

# Basal profile
rate_at_6am = settings.basal_profile.get_rate_at_time(6)

# Insulin sensitivity
isf_at_6am = settings.insulin_sensitivity_factor.get_factor_at_time(6)

# Carb ratio
ratio_at_6am = settings.carb_ratio.get_ratio_at_time(6)

# Targets
print(settings.target_glucose_min)      # Default: 70 mg/dL
print(settings.target_glucose_max)      # Default: 180 mg/dL
print(settings.correction_target)       # Default: 120 mg/dL

# Safety limits
print(settings.max_bolus)               # Default: 30 units
print(settings.max_basal)               # Default: 3.0 units/hour

# Convert to dictionary
settings_dict = settings.to_dict()
```

## Usage Examples

### Example 1: Complete Workflow

```python
from src.data_loader import GlookoDataLoader
from src.recommendation_engine import OmnipodRecommendationEngine
import json

# Load data
loader = GlookoDataLoader()
data = loader.load("my_glooko_export.json")

# Generate recommendations
engine = OmnipodRecommendationEngine(data)
report = engine.generate_summary_report()

# Save results
with open("my_recommendations.json", "w") as f:
    json.dump(report, f, indent=2, default=str)
```

### Example 2: Custom Analysis

```python
from src.analysis import GlucoseAnalyzer

analyzer = GlucoseAnalyzer(data)

# Get specific metrics
stats = analyzer.get_statistics()
mean_glucose = stats['mean']

tir = analyzer.get_time_in_range()
percentage_in_range = tir['time_in_range_percent']

# Analyze meals
meals = analyzer.detect_meal_response_pattern()
for pattern in meals:
    print(f"Meal at {pattern['meal_time']}: "
          f"{pattern['carbs']}g raised glucose by "
          f"{pattern['glucose_rise']:.0f} mg/dL")
```

### Example 3: Customizing Recommendations

```python
# Generate base recommendations
recommendations = engine.generate_recommendations()

# Modify if needed (before using!)
# ⚠️ CONSULT WITH YOUR MEDICAL TEAM FIRST

# Scale basal rates up by 10%
for hour in recommendations.basal_profile.rates:
    recommendations.basal_profile.rates[hour] *= 1.1

# Save modified recommendations
print(recommendations.to_dict())
```

## Algorithm Details

### Basal Rate Calculation

The engine calculates basal requirements by:

1. **Fasting Analysis**: Examines glucose trends during periods without meals
2. **Hourly Adjustment**: Identifies time-of-day patterns (dawn phenomenon)
3. **Safety Constraints**: Applies typical clinical ranges
4. **Circadian Adjustment**: Accounts for natural insulin sensitivity variations

### Insulin Sensitivity Factor (ISF)

ISF is derived by:

1. **Inverse Relationship**: Higher glucose correlates with higher ISF needed
2. **Correction Analysis**: Examines how glucose responds to corrections
3. **Time-of-Day Adjustment**: Accounts for dawn phenomenon, evening sensitivity
4. **Realistic Ranges**: Constrains to 1:50 to 1:150 range

### Carb-to-Insulin Ratio

Carb ratios calculated from:

1. **Meal Response Analysis**: Glucose rise following carb consumption
2. **Bolus Effectiveness**: Observed insulin-to-glucose relationships
3. **Time-of-Day Factors**: Insulin resistance varies throughout day
4. **Clinical Standards**: Compared to typical 1:10 to 1:25 ratios

## Command-Line Interface

```bash
# Generate recommendations
python -m src.cli data.json

# Save to file
python -m src.cli data.json -o recommendations.json

# Generate detailed report
python -m src.cli data.json -r

# JSON output
python -m src.cli data.json -f json

# Text output (default)
python -m src.cli data.json -f text
```

## Performance Considerations

- **Large Datasets**: Works efficiently with >1000 readings
- **Memory**: Loads entire dataset into memory
- **Processing Time**: Analysis typically completes in <1 second
- **Accuracy**: Improves with more data (minimum 1-2 weeks recommended)

## Limitations

- Requires minimum data to generate reliable recommendations
- Does not account for exercise, stress, or illness effects
- Assumes consistent meal timing
- Cannot detect medication changes
- Does not predict future glucose trends

## Error Handling

```python
from src.data_loader import GlookoDataLoader

try:
    data = loader.load("nonexistent.json")
except FileNotFoundError:
    print("File not found")
except ValueError as e:
    print(f"Invalid file format: {e}")
```

## Testing

Run tests:

```bash
python -m unittest discover tests/ -v
```

## Contributing

Contributions welcome! Follow PEP 8 and add tests for new features.

## Support

For issues or questions:
1. Check the [README.md](README.md)
2. Review [example_usage.py](example_usage.py)
3. Examine test files for usage patterns

---

**⚠️ DISCLAIMER**: This software is for educational purposes only. Do not use recommendations without consulting your healthcare provider.
