"""Data models for glucose readings and pump settings."""

from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, field
from enum import Enum


class GlucoseUnit(str, Enum):
    """Glucose measurement units."""
    MG_DL = "mg/dL"
    MMOL_L = "mmol/L"


class MealType(str, Enum):
    """Types of meals."""
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


@dataclass
class GlucoseReading:
    """A single glucose reading from Glooko."""
    timestamp: datetime
    value: float  # mg/dL
    unit: GlucoseUnit = GlucoseUnit.MG_DL
    source: str = "cgm"  # cgm, meter, etc.
    
    def to_mmol_l(self) -> float:
        """Convert to mmol/L if in mg/dL."""
        if self.unit == GlucoseUnit.MG_DL:
            return self.value / 18.0
        return self.value


@dataclass
class MealEvent:
    """Carbohydrate intake event."""
    timestamp: datetime
    carbs: float  # grams
    meal_type: Optional[MealType] = None
    notes: Optional[str] = None


@dataclass
class InsulinEvent:
    """Insulin injection or pump event."""
    timestamp: datetime
    amount: float  # units
    event_type: str = "bolus"  # bolus, basal, etc.


@dataclass
class BasalProfile:
    """Basal insulin rate schedule."""
    name: str
    rates: dict  # {hour: rate_in_units_per_hour}
    
    def get_rate_at_time(self, hour: int) -> float:
        """Get basal rate for a specific hour (0-23)."""
        return self.rates.get(hour, 0.0)


@dataclass
class InsulinSensitivityFactor:
    """Insulin sensitivity (correction factor)."""
    name: str
    factors: dict  # {hour: correction_factor}
    
    def get_factor_at_time(self, hour: int) -> float:
        """Get ISF for a specific hour."""
        return self.factors.get(hour, 100.0)  # Default 1:100


@dataclass
class CarbRatio:
    """Carbohydrate to insulin ratio."""
    name: str
    ratios: dict  # {hour: grams_per_unit}
    
    def get_ratio_at_time(self, hour: int) -> float:
        """Get carb ratio for a specific hour."""
        return self.ratios.get(hour, 15.0)  # Default 1:15


@dataclass
class OmnipodSettings:
    """Omnipod pump recommended settings."""
    basal_profile: BasalProfile
    insulin_sensitivity_factor: InsulinSensitivityFactor
    carb_ratio: CarbRatio
    target_glucose_min: float = 70.0  # mg/dL
    target_glucose_max: float = 180.0  # mg/dL
    correction_target: float = 120.0  # mg/dL
    max_bolus: float = 30.0  # units
    max_basal: float = 3.0  # units/hour
    active_insulin_time: float = 4.0  # hours
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert settings to dictionary."""
        return {
            "basal_profile": {
                "name": self.basal_profile.name,
                "rates": self.basal_profile.rates,
            },
            "insulin_sensitivity_factor": {
                "name": self.insulin_sensitivity_factor.name,
                "factors": self.insulin_sensitivity_factor.factors,
            },
            "carb_ratio": {
                "name": self.carb_ratio.name,
                "ratios": self.carb_ratio.ratios,
            },
            "target_glucose_min": self.target_glucose_min,
            "target_glucose_max": self.target_glucose_max,
            "correction_target": self.correction_target,
            "max_bolus": self.max_bolus,
            "max_basal": self.max_basal,
            "active_insulin_time": self.active_insulin_time,
            "warnings": self.warnings,
        }


@dataclass
class GloocolData:
    """Container for all Glooko data."""
    glucose_readings: List[GlucoseReading] = field(default_factory=list)
    meals: List[MealEvent] = field(default_factory=list)
    insulin_events: List[InsulinEvent] = field(default_factory=list)
    
    def get_readings_in_range(self, start: datetime, end: datetime) -> List[GlucoseReading]:
        """Get glucose readings within a time range."""
        return [r for r in self.glucose_readings if start <= r.timestamp <= end]
    
    def get_time_range(self) -> tuple:
        """Get the min and max timestamps in the dataset."""
        if not self.glucose_readings:
            return None, None
        readings_times = [r.timestamp for r in self.glucose_readings]
        return min(readings_times), max(readings_times)
