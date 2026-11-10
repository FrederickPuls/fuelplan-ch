"""Garmin-Export als CSV: Aktivitäten und Tageswerte bis und mit config.CSV_LAST_DAY.

Nur die zwei CSVs in data/ werden gelesen, nie der Rohexport. Die Daten gehen
nicht ans Modell, nur die daraus gebildete Tageszusammenfassung.
"""

from __future__ import annotations

import csv
from datetime import date, time
from pathlib import Path

from fuelplan import config
from fuelplan.models import Activity, ActivityType, DailySummary, Source
from fuelplan.training import TrainingDataError

CSV_TYPES = {
    "running": ActivityType.RUNNING,
    "strength_training": ActivityType.STRENGTH,
    "cycling": ActivityType.CYCLING,
    "hiking": ActivityType.HIKING,
    "other": ActivityType.OTHER,
}


def _f(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _i(value: str | None) -> int | None:
    v = _f(value)
    return None if v is None else int(v)


def _time(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


def read_activities(path: Path = config.ACTIVITIES_CSV, last_day: date = config.CSV_LAST_DAY) -> list[Activity]:
    if not path.exists():
        raise TrainingDataError(f"Garmin-CSV fehlt: {path}")
    out: list[Activity] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            d = date.fromisoformat(row["date"])
            if d > last_day:
                continue
            out.append(
                Activity(
                    date=d,
                    time=_time(row.get("time")),
                    type=CSV_TYPES.get(row["type"], ActivityType.UNKNOWN),
                    name=row.get("name", ""),
                    duration_min=_f(row["duration_min"]) or 0.0,
                    distance_km=_f(row.get("distance_km")) or 0.0,
                    avg_hr=_f(row.get("avg_hr")),
                    max_hr=_f(row.get("max_hr")),
                    kcal=_f(row.get("kcal")),
                    training_load=_f(row.get("training_load")),
                    aerobic_te=_f(row.get("aerobic_te")),
                    anaerobic_te=_f(row.get("anaerobic_te")),
                    te_label=(row.get("te_label") or None),
                    source=Source.GARMIN_CSV,
                )
            )
    return out


def read_daily(path: Path = config.DAILY_CSV, last_day: date = config.CSV_LAST_DAY) -> dict[date, DailySummary]:
    if not path.exists():
        return {}
    out: dict[date, DailySummary] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            d = date.fromisoformat(row["date"])
            if d > last_day:
                continue
            out[d] = DailySummary(
                date=d,
                total_kcal=_f(row.get("total_kcal")),
                active_kcal=_f(row.get("active_kcal")),
                bmr_kcal=_f(row.get("bmr_kcal")),
                steps=_i(row.get("steps")),
                resting_hr=_i(row.get("resting_hr")),
                avg_stress=_i(row.get("avg_stress")),
            )
    return out


class GarminCsvSource:
    """ActivitySource über die CSVs; liest lazy und cached im Objekt."""

    def __init__(self, activities_path: Path = config.ACTIVITIES_CSV, daily_path: Path = config.DAILY_CSV,
                 last_day: date = config.CSV_LAST_DAY) -> None:
        self._activities_path = activities_path
        self._daily_path = daily_path
        self.last_day = last_day
        self._activities: list[Activity] | None = None
        self._daily: dict[date, DailySummary] | None = None

    def activities(self, oldest: date, newest: date) -> list[Activity]:
        if self._activities is None:
            self._activities = read_activities(self._activities_path, self.last_day)
        return [a for a in self._activities if oldest <= a.date <= newest]

    def daily(self, day: date) -> DailySummary | None:
        if self._daily is None:
            self._daily = read_daily(self._daily_path, self.last_day)
        return self._daily.get(day)
