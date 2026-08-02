# GlucoLens - Getting Started Guide

## What is GlucoLens?

GlucoLens is an intelligent diabetes data analysis system that:

1. **Imports Glooko Data**: Reads glucose readings, meals, and insulin data from Glooko exports
2. **Analyzes Patterns**: Identifies glucose trends, meal responses, and personal patterns
3. **Generates Recommendations**: Creates personalized Omnipod pump settings based on your data

## Quick Start (5 minutes)

### 1. Install Dependencies

```bash
cd /Users/ravi/WORKSPACES/GLUCOLENS
pip install -r requirements.txt
```

### 2. Run with Sample Data

```bash
python -m src.cli data/sample_glooko.json -r
```

You'll see:
- Glucose statistics (mean, variability, etc.)
- Time in range analysis
- Recommended basal rates by hour
- Recommended insulin sensitivity factors
- Recommended carb-to-insulin ratios

### 3. Try with Your Data

```bash
# Export your Glooko data as CSV or JSON
# Then run:
python -m src.cli your_glooko_export.json -r -o my_recommendations.json
```

## File Organization

```
glucolens/
├── src/                    # Main source code
│   ├── models.py          # Data structures
│   ├── data_loader.py     # Import Glooko data
│   ├── analysis.py        # Analyze glucose patterns
│   ├── recommendation_engine.py  # Generate recommendations
│   └── cli.py             # Command-line interface
├── tests/                 # Unit tests
├── data/                  # Sample data files
├── docs/                  # Documentation
├── README.md              # Project overview
├── example_usage.py       # Python API examples
└── requirements.txt       # Dependencies
```

## How to Use

### Via Command Line

#### Basic Analysis
```bash
python -m src.cli my_data.json
```

#### Full Report with Time in Range
```bash
python -m src.cli my_data.json -r
```

#### Save to File
```bash
python -m src.cli my_data.json -r -o my_results.json
```

#### JSON Output
```bash
python -m src.cli my_data.json -f json > results.json
```

### Via Python Script

```python
from src.data_loader import GlookoDataLoader
from src.recommendation_engine import OmnipodRecommendationEngine

# Load your Glooko export
loader = GlookoDataLoader()
data = loader.load("my_glooko_export.json")

# Generate recommendations
engine = OmnipodRecommendationEngine(data)
report = engine.generate_summary_report()

# Access specific metrics
basal = report['recommendations']['basal_profile']['rates']
isf = report['recommendations']['insulin_sensitivity_factor']['factors']
carb_ratio = report['recommendations']['carb_ratio']['ratios']

print(f"Recommended basal at 8am: {basal['8']} units/hour")
```

## Preparing Your Glooko Export

### CSV Format

Required columns:
- `timestamp`: Date/time (format: "2024-01-15 08:00:00")
- `glucose_value`: Glucose reading in mg/dL
- Optional: `source` (cgm, meter, etc.)

```csv
timestamp,glucose_value,source
2024-01-15 08:00:00,120,cgm
2024-01-15 08:05:00,125,cgm
2024-01-15 12:00:00,128,cgm
```

For meals, include `carbs` column:
```csv
timestamp,carbs,meal_type
2024-01-15 08:00:00,45,breakfast
2024-01-15 12:00:00,60,lunch
```

For insulin, include `insulin_amount` column:
```csv
timestamp,insulin_amount,type
2024-01-15 08:05:00,4.0,bolus
2024-01-15 12:05:00,5.0,bolus
```

### JSON Format

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
      "notes": "Optional"
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

## Understanding the Output

### Basal Profile
Your hourly insulin delivery rates:
```
00:00 - 0.40 units/hour  (Night)
06:00 - 0.55 units/hour  (Morning - dawn phenomenon)
12:00 - 0.50 units/hour  (Afternoon)
18:00 - 0.53 units/hour  (Evening)
```

### Insulin Sensitivity Factor (ISF)
How much one unit of insulin lowers your glucose:
```
06:00 - 1:85 mg/dL per unit   (Resistant morning)
12:00 - 1:100 mg/dL per unit  (Standard)
18:00 - 1:95 mg/dL per unit   (Moderate)
22:00 - 1:110 mg/dL per unit  (Sensitive evening)
```
Meaning: 1 unit of insulin at 6am will lower glucose ~85 mg/dL.

### Carb-to-Insulin Ratio
Grams of carbs covered by one unit of insulin:
```
07:00 - 1 unit per 12.7g carbs  (Morning - more resistant)
12:00 - 1 unit per 15.0g carbs  (Standard)
18:00 - 1 unit per 16.5g carbs  (Evening - more sensitive)
22:00 - 1 unit per 16.5g carbs  (Night)
```
Meaning: At 7am, 1 unit covers about 12.7g of carbs.

### Time in Range
Percentage of readings within target glucose range (70-180 mg/dL):
```
In Range:  95.3%  ✓ Excellent
Below:     2.1%   - Low glucose events
Above:     2.6%   - High glucose events
```

## Interpretation Guidelines

### What Good Numbers Look Like

| Metric | Target | Status |
|--------|--------|--------|
| Time In Range | >70% | Excellent goal |
| Glucose Mean | 100-150 mg/dL | Healthy range |
| Std Dev | <30 mg/dL | Good stability |
| Low Events | <4% | Acceptable |
| High Events | <10% | Good control |

### Common Patterns

**Dawn Phenomenon**
- Higher glucose at 6-8am
- Lower ISF recommended
- Higher basal rate needed

**Evening Sensitivity**
- Lower glucose in evening
- Higher ISF (less insulin needed)
- Lower carb ratio (more carbs per unit)

**Post-Meal Spike**
- Peak glucose 1-2 hours after meals
- Used to calibrate carb ratios
- Normal insulin peak action

## Data Requirements

For best results, provide:

- **Minimum**: 3-5 days of data
- **Recommended**: 2-4 weeks of data
- **Ideal**: 1-3 months of continuous data

More data = more accurate recommendations because:
- Captures daily variations
- Identifies time-of-day patterns
- Shows weekend vs. weekday differences
- Accounts for seasonal changes

## Advanced Usage

### Custom Analysis

```python
from src.analysis import GlucoseAnalyzer

analyzer = GlucoseAnalyzer(data)

# Get specific hour analysis
hourly = analyzer.get_hourly_averages()
morning_avg = hourly[8]  # 8am glucose

# Detect meal impacts
meals = analyzer.detect_meal_response_pattern()
for meal in meals:
    rise = meal['glucose_rise']
    carbs = meal['carbs']
    ratio = rise / carbs  # mg/dL per gram

# Find problematic times
lows = analyzer.detect_low_glucose_events(threshold=70)
print(f"Low glucose {len(lows)} times")
```

### Batch Processing

```python
import glob
from pathlib import Path

# Process multiple Glooko exports
for file in glob.glob("glooko_exports/*.json"):
    data = loader.load(file)
    engine = OmnipodRecommendationEngine(data)
    report = engine.generate_summary_report()
    
    # Save individual report
    output = Path(file).stem + "_recommendations.json"
    with open(output, 'w') as f:
        json.dump(report, f, indent=2)
```

## Troubleshooting

### "No module named 'src'"
Solution: Run from the project directory
```bash
cd /Users/ravi/WORKSPACES/GLUCOLENS
python -m src.cli ...
```

### "FileNotFoundError"
Solution: Use full paths or ensure files exist
```bash
python -m src.cli /full/path/to/glooko_export.json
ls data/  # Verify files exist
```

### Empty Results
Possible causes:
1. No glucose readings in file
2. Wrong column names
3. Invalid date format

Solution: Check file format, see [Preparing Your Glooko Export](#preparing-your-glooko-export)

### Very High/Low Recommendations
Possible causes:
1. Insufficient data (< 1 week)
2. Extreme outliers
3. Data entry errors

Solution: Clean data, use more representative period

## Running Tests

Verify everything works:

```bash
python -m unittest discover tests/ -v
```

Expected output:
```
test_glucose_conversion ... ok
test_statistics ... ok
test_time_in_range ... ok
... (7 tests total)
Ran 7 tests in 0.001s - OK
```

## Key Concepts

### Basal Rate
Continuous background insulin delivery
- Prevents glucose rise during fasting
- Typically 40-70% of daily insulin
- Adjusted by hour for circadian patterns

### Bolus
Insulin dose with meals
- Covers carbs eaten
- Corrects high glucose
- Usually 30-40% of daily insulin

### Insulin Sensitivity Factor (ISF)
Correction factor - how much glucose one unit lowers
- Varies throughout day
- Lower when insulin resistant (dawn)
- Higher when more sensitive (night)

### Carb-to-Insulin Ratio
Meal coverage - grams of carbs one unit covers
- Typically 1:10 to 1:25 range
- Related to ISF (higher ISF = higher ratio)

## Security & Privacy

- **No Cloud**: All data processed locally
- **No Sharing**: Your data stays on your device
- **Open Source**: Code you can review
- **Offline**: Works without internet

## Medical Disclaimer

⚠️ **IMPORTANT**: 

- This software is **educational only**
- **DO NOT** use recommendations without medical consultation
- **ALWAYS** discuss changes with your healthcare provider
- Diabetes management requires professional oversight
- Never adjust insulin based solely on this software

Before implementing any recommendations:
1. ✓ Discuss with your endocrinologist
2. ✓ Verify settings on your pump device
3. ✓ Monitor closely for the first week
4. ✓ Adjust based on real-world results

## Getting Help

1. **Check [README.md](README.md)** - Project overview
2. **Review [API.md](docs/API.md)** - Technical documentation
3. **Run [example_usage.py](example_usage.py)** - Working examples
4. **Examine [tests/](tests/)** - Unit tests show usage

## Next Steps

1. ✓ Export your Glooko data
2. ✓ Run example with sample data
3. ✓ Run with your own data
4. ✓ Review recommendations
5. ✓ Discuss with doctor
6. ✓ Implement gradual changes

## Contributing

Found a bug or want to improve?

1. Check code in `src/` directory
2. Add tests to `tests/`
3. Submit improvements

## Support Resources

- **Diabetes Tech Community**: Useful for discussing CGM/pump settings
- **Your Endocrinologist**: For medical guidance
- **Omnipod Support**: For pump-specific questions
- **This README**: For software usage

---

**Last Updated**: August 2, 2026  
**Version**: 1.0.0  
**Status**: Ready for use (educational purposes)
