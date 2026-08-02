#!/usr/bin/env python
"""
Example usage script for GlucoLens.

This script demonstrates how to use the GlucoLens library
to analyze Glooko data and generate Omnipod recommendations.
"""

import sys
from pathlib import Path
import json

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent))

from src.data_loader import GlookoDataLoader
from src.recommendation_engine import OmnipodRecommendationEngine


def main():
    """Run analysis and generate recommendations."""
    
    # Example 1: Load JSON data
    print("=" * 60)
    print("EXAMPLE 1: Loading Glooko JSON Export")
    print("=" * 60)
    
    loader = GlookoDataLoader()
    data = loader.load("data/sample_glooko.json")
    
    print(f"Loaded data:")
    print(f"  - Glucose readings: {len(data.glucose_readings)}")
    print(f"  - Meals: {len(data.meals)}")
    print(f"  - Insulin events: {len(data.insulin_events)}")
    print()
    
    # Example 2: Analyze glucose patterns
    print("=" * 60)
    print("EXAMPLE 2: Analyzing Glucose Patterns")
    print("=" * 60)
    
    engine = OmnipodRecommendationEngine(data)
    analyzer = engine.analyzer
    
    # Get basic statistics
    stats = analyzer.get_statistics()
    print("\nGlucose Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value:.1f}")
    
    # Get time in range
    tir = analyzer.get_time_in_range()
    print("\nTime In Range Analysis:")
    for key, value in tir.items():
        print(f"  {key}: {value:.1f}%")
    
    print()
    
    # Example 3: Generate recommendations
    print("=" * 60)
    print("EXAMPLE 3: Generating Omnipod Recommendations")
    print("=" * 60)
    print()
    
    recommendations = engine.generate_recommendations()
    
    print("Basal Profile (sample hours):")
    for hour in [0, 6, 12, 18]:
        rate = recommendations.basal_profile.rates[hour]
        print(f"  {hour:02d}:00 - {rate:.2f} units/hour")
    
    print("\nInsulin Sensitivity Factor (sample hours):")
    for hour in [0, 6, 12, 18]:
        factor = recommendations.insulin_sensitivity_factor.factors[hour]
        print(f"  {hour:02d}:00 - 1:{factor:.0f} mg/dL per unit")
    
    print("\nCarb-to-Insulin Ratio (sample hours):")
    for hour in [7, 12, 18, 22]:
        ratio = recommendations.carb_ratio.ratios[hour]
        print(f"  {hour:02d}:00 - 1 unit per {ratio:.1f}g carbs")
    
    print("\nTarget Settings:")
    print(f"  Target range: {recommendations.target_glucose_min:.0f} - "
          f"{recommendations.target_glucose_max:.0f} mg/dL")
    print(f"  Correction target: {recommendations.correction_target:.0f} mg/dL")
    print(f"  Max bolus: {recommendations.max_bolus:.1f} units")
    print(f"  Max basal: {recommendations.max_basal:.2f} units/hour")
    print()
    
    # Example 4: Generate full report
    print("=" * 60)
    print("EXAMPLE 4: Full Analysis Report")
    print("=" * 60)
    print()
    
    report = engine.generate_summary_report()
    
    # Save to file
    output_file = "sample_recommendations.json"
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"Full report saved to: {output_file}")
    print("\nReport Summary:")
    print(f"  Data points analyzed: {report['data_summary']['total_readings']}")
    print(f"  Meals detected: {report['data_summary']['total_meals']}")
    print(f"  Meal patterns: {report['meal_patterns_detected']}")
    print(f"  Low glucose events: {report['low_glucose_events']}")
    print()
    
    # Example 5: Using the Python API
    print("=" * 60)
    print("EXAMPLE 5: Using Different Data Sources")
    print("=" * 60)
    print()
    
    # You can load CSV files too
    print("Supported file formats:")
    print("  - CSV: data/sample_glucose.csv")
    print("  - JSON: data/sample_glooko.json")
    print()
    print("Load different files with:")
    print("  data = loader.load('path/to/file.csv')")
    print("  data = loader.load('path/to/file.json')")
    print()
    
    print("=" * 60)
    print("Analysis Complete!")
    print("=" * 60)
    
    # ⚠️ IMPORTANT DISCLAIMER
    print("\n" + "!" * 60)
    print("⚠️  DISCLAIMER")
    print("!" * 60)
    print("""
These recommendations are for EDUCATIONAL PURPOSES ONLY.

DO NOT use these recommendations to adjust your Omnipod pump
or any other insulin delivery device without professional
medical supervision.

ALWAYS consult with your endocrinologist or diabetes care team
before making any changes to your pump settings.

Diabetes management requires professional oversight and
individualized care based on your specific medical situation.
    """)
    print("!" * 60)


if __name__ == "__main__":
    main()
