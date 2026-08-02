"""Tests for GlucoLens modules."""

import unittest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path to import src package
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    GlucoseReading, MealEvent, InsulinEvent, GlucoseUnit,
    MealType, GloocolData, BasalProfile, InsulinSensitivityFactor,
    CarbRatio, OmnipodSettings
)
from src.analysis import GlucoseAnalyzer


class TestModels(unittest.TestCase):
    """Test data models."""
    
    def test_glucose_reading_creation(self):
        """Test glucose reading creation."""
        now = datetime.now()
        reading = GlucoseReading(
            timestamp=now,
            value=125.0,
            unit=GlucoseUnit.MG_DL
        )
        self.assertEqual(reading.value, 125.0)
        self.assertEqual(reading.unit, GlucoseUnit.MG_DL)
    
    def test_glucose_conversion(self):
        """Test glucose unit conversion."""
        reading = GlucoseReading(
            timestamp=datetime.now(),
            value=180.0,
            unit=GlucoseUnit.MG_DL
        )
        mmol = reading.to_mmol_l()
        self.assertAlmostEqual(mmol, 10.0, places=1)
    
    def test_meal_event_creation(self):
        """Test meal event creation."""
        now = datetime.now()
        meal = MealEvent(
            timestamp=now,
            carbs=45.0,
            meal_type=MealType.LUNCH
        )
        self.assertEqual(meal.carbs, 45.0)
        self.assertEqual(meal.meal_type, MealType.LUNCH)
    
    def test_basal_profile(self):
        """Test basal profile."""
        rates = {i: 0.5 for i in range(24)}
        profile = BasalProfile(name="Test", rates=rates)
        self.assertEqual(profile.get_rate_at_time(12), 0.5)


class TestAnalysis(unittest.TestCase):
    """Test analysis functions."""
    
    def setUp(self):
        """Set up test data."""
        self.data = GloocolData()
        base_time = datetime.now()
        
        # Add sample glucose readings
        for i in range(24):
            self.data.glucose_readings.append(
                GlucoseReading(
                    timestamp=base_time + timedelta(hours=i),
                    value=100 + (i % 10) * 10,
                    unit=GlucoseUnit.MG_DL
                )
            )
        
        # Add meals
        self.data.meals.append(
            MealEvent(
                timestamp=base_time + timedelta(hours=8),
                carbs=45.0,
                meal_type=MealType.BREAKFAST
            )
        )
        
        # Add insulin
        self.data.insulin_events.append(
            InsulinEvent(
                timestamp=base_time + timedelta(hours=8, minutes=5),
                amount=4.0,
                event_type="bolus"
            )
        )
    
    def test_statistics(self):
        """Test glucose statistics calculation."""
        analyzer = GlucoseAnalyzer(self.data)
        stats = analyzer.get_statistics()
        
        self.assertIn("mean", stats)
        self.assertIn("min", stats)
        self.assertIn("max", stats)
        self.assertGreater(stats["mean"], 0)
    
    def test_time_in_range(self):
        """Test time in range calculation."""
        analyzer = GlucoseAnalyzer(self.data)
        tir = analyzer.get_time_in_range()
        
        self.assertIn("time_in_range_percent", tir)
        self.assertGreaterEqual(tir["time_in_range_percent"], 0)
        self.assertLessEqual(tir["time_in_range_percent"], 100)
    
    def test_hourly_averages(self):
        """Test hourly average calculation."""
        analyzer = GlucoseAnalyzer(self.data)
        hourly = analyzer.get_hourly_averages()
        
        self.assertEqual(len(hourly), 24)
        for hour in range(24):
            self.assertIn(hour, hourly)


if __name__ == "__main__":
    unittest.main()
