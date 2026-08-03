"""Load and parse Glooko diabetes data from various formats."""

import csv
import json
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from .models import (
    GlucoseReading, MealEvent, InsulinEvent, GlucoseUnit,
    MealType, GloocolData
)


class GlookoDataLoader:
    """Loader for Glooko exported data."""
    
    DATE_FORMATS = [
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M",
    ]
    
    @staticmethod
    def parse_datetime(date_string: str) -> datetime:
        """Try to parse datetime string with multiple formats."""
        for fmt in GlookoDataLoader.DATE_FORMATS:
            try:
                return datetime.strptime(date_string.strip(), fmt)
            except ValueError:
                continue
        raise ValueError(f"Unable to parse date: {date_string}")
    
    @classmethod
    def load_csv(cls, file_path: Union[str, Path]) -> GloocolData:
        """Load Glooko CSV export file."""
        file_path = Path(file_path)
        data = GloocolData()
        
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cls._process_csv_row(row, data)
        
        return data
    
    @classmethod
    def _process_csv_row(cls, row: dict, data: GloocolData) -> None:
        """Process a single CSV row and add to data."""
        # Detect row type based on available columns
        if 'Glucose Value' in row or 'glucose_value' in row:
            cls._parse_glucose_row(row, data)
        elif 'Carbohydrates' in row or 'carbs' in row:
            cls._parse_meal_row(row, data)
        elif 'Insulin' in row or 'insulin_amount' in row:
            cls._parse_insulin_row(row, data)
    
    @classmethod
    def _parse_glucose_row(cls, row: dict, data: GloocolData) -> None:
        """Parse glucose reading from CSV row."""
        # Try different column name conventions
        value_key = next((k for k in row if 'glucose' in k.lower() and 'value' in k.lower()), None)
        time_key = next((k for k in row if k.lower() in ['timestamp', 'time', 'datetime']), None)
        
        if not value_key or not time_key:
            return
        
        try:
            value = float(row[value_key].strip())
            timestamp = cls.parse_datetime(row[time_key])
            reading = GlucoseReading(
                timestamp=timestamp,
                value=value,
                unit=GlucoseUnit.MG_DL,
                source=row.get('Source', 'cgm').lower()
            )
            data.glucose_readings.append(reading)
        except (ValueError, KeyError):
            pass
    
    @classmethod
    def _parse_meal_row(cls, row: dict, data: GloocolData) -> None:
        """Parse meal event from CSV row."""
        carbs_key = next((k for k in row if 'carb' in k.lower()), None)
        time_key = next((k for k in row if k.lower() in ['timestamp', 'time', 'datetime']), None)
        
        if not carbs_key or not time_key:
            return
        
        try:
            carbs = float(row[carbs_key].strip())
            timestamp = cls.parse_datetime(row[time_key])
            meal = MealEvent(
                timestamp=timestamp,
                carbs=carbs,
                meal_type=None,
                notes=row.get('Notes', '')
            )
            data.meals.append(meal)
        except (ValueError, KeyError):
            pass
    
    @classmethod
    def _parse_insulin_row(cls, row: dict, data: GloocolData) -> None:
        """Parse insulin event from CSV row."""
        insulin_key = next((k for k in row if 'insulin' in k.lower()), None)
        time_key = next((k for k in row if k.lower() in ['timestamp', 'time', 'datetime']), None)
        
        if not insulin_key or not time_key:
            return
        
        try:
            amount = float(row[insulin_key].strip())
            timestamp = cls.parse_datetime(row[time_key])
            event_type = row.get('Type', 'bolus').lower()
            insulin = InsulinEvent(
                timestamp=timestamp,
                amount=amount,
                event_type=event_type
            )
            data.insulin_events.append(insulin)
        except (ValueError, KeyError):
            pass
    
    @classmethod
    def load_json(cls, file_path: Union[str, Path]) -> GloocolData:
        """Load Glooko JSON export file."""
        file_path = Path(file_path)
        data = GloocolData()
        
        with open(file_path, 'r') as f:
            content = json.load(f)

        if content.get('patient_name'):
            data.patient_name = str(content['patient_name']).strip() or None

        # Process glucose readings
        if 'glucose_readings' in content:
            for item in content['glucose_readings']:
                try:
                    reading = GlucoseReading(
                        timestamp=cls.parse_datetime(item['timestamp']),
                        value=float(item['value']),
                        unit=GlucoseUnit(item.get('unit', 'mg/dL')),
                        source=item.get('source', 'cgm')
                    )
                    data.glucose_readings.append(reading)
                except (ValueError, KeyError):
                    pass
        
        # Process meals
        if 'meals' in content:
            for item in content['meals']:
                try:
                    meal = MealEvent(
                        timestamp=cls.parse_datetime(item['timestamp']),
                        carbs=float(item['carbs']),
                        meal_type=MealType(item.get('meal_type')) if item.get('meal_type') else None,
                        notes=item.get('notes')
                    )
                    data.meals.append(meal)
                except (ValueError, KeyError):
                    pass
        
        # Process insulin events
        if 'insulin_events' in content:
            for item in content['insulin_events']:
                try:
                    insulin = InsulinEvent(
                        timestamp=cls.parse_datetime(item['timestamp']),
                        amount=float(item['amount']),
                        event_type=item.get('event_type', 'bolus')
                    )
                    data.insulin_events.append(insulin)
                except (ValueError, KeyError):
                    pass
        
        return data
    
    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Parse a possibly-empty/non-numeric CSV cell to a float, or None."""
        if value is None or value == '':
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _read_glooko_rows(file_path: Path):
        """Read a real Glooko export CSV.

        Real exports are UTF-8 with a BOM, and have a leading
        'Name:...,Date Range:...' metadata line before the actual header row.
        """
        with open(file_path, 'r', encoding='utf-8-sig', newline='') as f:
            next(f, None)  # metadata line
            reader = csv.DictReader(f)
            for row in reader:
                yield row

    @classmethod
    def _parse_glooko_cgm_file(cls, file_path: Path, data: GloocolData) -> None:
        for row in cls._read_glooko_rows(file_path):
            try:
                timestamp = cls.parse_datetime(row['Timestamp'])
                value = float(row['CGM Glucose Value (mg/dl)'])
            except (ValueError, KeyError):
                continue
            data.glucose_readings.append(
                GlucoseReading(timestamp=timestamp, value=value, unit=GlucoseUnit.MG_DL, source='cgm')
            )

    @classmethod
    def _parse_glooko_bg_file(cls, file_path: Path, data: GloocolData) -> None:
        for row in cls._read_glooko_rows(file_path):
            try:
                timestamp = cls.parse_datetime(row['Timestamp'])
                value = float(row['Glucose Value (mg/dl)'])
            except (ValueError, KeyError):
                continue
            data.glucose_readings.append(
                GlucoseReading(timestamp=timestamp, value=value, unit=GlucoseUnit.MG_DL, source='meter')
            )

    @classmethod
    def _parse_glooko_bolus_file(cls, file_path: Path, data: GloocolData) -> None:
        for row in cls._read_glooko_rows(file_path):
            try:
                timestamp = cls.parse_datetime(row['Timestamp'])
            except (ValueError, KeyError):
                continue

            carbs = cls._safe_float(row.get('Carbs Input (g)'))
            if carbs:
                data.meals.append(MealEvent(timestamp=timestamp, carbs=carbs))

            delivered = cls._safe_float(row.get('Insulin Delivered (U)'))
            if delivered:
                data.insulin_events.append(
                    InsulinEvent(timestamp=timestamp, amount=delivered, event_type='bolus')
                )

    @classmethod
    def _parse_glooko_daily_insulin_file(cls, file_path: Path, data: GloocolData) -> None:
        """Daily aggregate totals -- the only source of basal dose data in a
        real Glooko/Omnipod 5 export, since continuous automated basal
        delivery isn't logged as discrete events anywhere else."""
        for row in cls._read_glooko_rows(file_path):
            try:
                timestamp = cls.parse_datetime(row['Timestamp'])
            except (ValueError, KeyError):
                continue

            basal_total = cls._safe_float(row.get('Total Basal (U)'))
            if basal_total:
                data.insulin_events.append(
                    InsulinEvent(timestamp=timestamp, amount=basal_total, event_type='basal')
                )

    @classmethod
    def _parse_glooko_manual_food_file(cls, file_path: Path, data: GloocolData) -> None:
        for row in cls._read_glooko_rows(file_path):
            try:
                timestamp = cls.parse_datetime(row['Timestamp'])
            except (ValueError, KeyError):
                continue
            carbs = cls._safe_float(row.get('Carbs (g)'))
            if carbs:
                data.meals.append(MealEvent(timestamp=timestamp, carbs=carbs, notes=row.get('Name')))

    @classmethod
    def _parse_glooko_manual_insulin_file(cls, file_path: Path, data: GloocolData) -> None:
        for row in cls._read_glooko_rows(file_path):
            try:
                timestamp = cls.parse_datetime(row['Timestamp'])
            except (ValueError, KeyError):
                continue
            amount = cls._safe_float(row.get('Value'))
            if amount:
                event_type = (row.get('Insulin Type') or 'bolus').lower()
                data.insulin_events.append(
                    InsulinEvent(timestamp=timestamp, amount=amount, event_type=event_type)
                )

    @staticmethod
    def _extract_patient_name(file_path: Path) -> Optional[str]:
        """Parse the patient name from a Glooko export's leading metadata
        line, e.g. 'Name:Jane Doe,Date Range:2026-01-01 - 2026-01-14'."""
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                first_line = f.readline()
        except OSError:
            return None

        match = re.match(r'Name:([^,]*),', first_line.strip())
        if not match:
            return None
        name = match.group(1).strip()
        return name or None

    @classmethod
    def _load_glooko_export_dir(cls, root: Path, data: GloocolData) -> None:
        for file_path in sorted(root.glob('**/*.csv')):
            name = cls._extract_patient_name(file_path)
            if name:
                data.patient_name = name
                break

        for file_path in sorted(root.glob('**/cgm_data*.csv')):
            cls._parse_glooko_cgm_file(file_path, data)
        for file_path in sorted(root.glob('**/bg_data*.csv')):
            cls._parse_glooko_bg_file(file_path, data)
        for file_path in sorted(root.glob('**/bolus_data*.csv')):
            cls._parse_glooko_bolus_file(file_path, data)
        for file_path in sorted(root.glob('**/insulin_data*.csv')):
            cls._parse_glooko_daily_insulin_file(file_path, data)
        for file_path in sorted(root.glob('**/food_data*.csv')):
            cls._parse_glooko_manual_food_file(file_path, data)
        for file_path in sorted(root.glob('**/manual_insulin_data*.csv')):
            cls._parse_glooko_manual_insulin_file(file_path, data)

    @classmethod
    def load_glooko_export(cls, path: Union[str, Path]) -> GloocolData:
        """Load a real multi-file Glooko export (a directory, or a .zip of one).

        A real Glooko export isn't a single CSV/JSON -- it's several files
        (cgm_data*.csv, bg_data*.csv, Insulin data/bolus_data*.csv,
        Insulin data/insulin_data*.csv, Manual data/*.csv), each with a
        leading 'Name:...,Date Range:...' metadata line before the header.
        Continuous automated pump basal delivery (e.g. Omnipod 5 in
        Automated Mode) isn't logged as discrete events at all -- only
        insulin_data*.csv's daily 'Total Basal (U)' aggregate captures it.
        """
        path = Path(path)
        data = GloocolData()

        if path.is_file() and path.suffix.lower() == '.zip':
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(path) as zf:
                    zf.extractall(tmp_dir)
                cls._load_glooko_export_dir(Path(tmp_dir), data)
        elif path.is_dir():
            cls._load_glooko_export_dir(path, data)
        else:
            raise ValueError(f"Not a Glooko export directory or zip: {path}")

        return data

    @classmethod
    def load(cls, file_path: Union[str, Path]) -> GloocolData:
        """Auto-detect and load Glooko data.

        Accepts a single generic CSV/JSON export, or a real multi-file
        Glooko export (a directory, or a .zip of one).
        """
        file_path = Path(file_path)

        if file_path.is_dir() or file_path.suffix.lower() == '.zip':
            return cls.load_glooko_export(file_path)
        elif file_path.suffix.lower() == '.csv':
            return cls.load_csv(file_path)
        elif file_path.suffix.lower() == '.json':
            return cls.load_json(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}")
