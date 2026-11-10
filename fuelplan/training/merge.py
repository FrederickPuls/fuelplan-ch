"""Stichtag-Logik: Tage ≤ CSV_LAST_DAY aus der CSV, danach aus intervals.icu.

Keine Aktivität doppelt; „heute“ = Datum in Europe/Zurich; 7-Tage-Schnitt der
Trainingslast über den Stichtag hinweg aus beiden Quellen. Für Tage, die ganz
in der CSV liegen, wird intervals.icu nicht abgefragt.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time, timedelta
from typing import Protocol

from fuelplan import config
from fuelplan.models import Activity, DailySummary, DayContext
from fuelplan.nutrition import rules as R


class ActivitySource(Protocol):
    def activities(self, oldest: date, newest: date) -> list[Activity]: ...


def _dedupe(acts: list[Activity]) -> list[Activity]:
    """Gleiche Aktivität nur einmal: gleiche externe ID oder gleicher Tag/Typ/Dauer/Distanz."""
    seen_ids: set[str] = set()
    seen_keys: set[tuple] = set()
    out: list[Activity] = []
    for a in acts:
        key = (a.date, a.type, round(a.duration_min), round(a.distance_km, 1))
        if (a.external_id and a.external_id in seen_ids) or key in seen_keys:
            continue
        if a.external_id:
            seen_ids.add(a.external_id)
        seen_keys.add(key)
        out.append(a)
    return out


def collect_activities(oldest: date, newest: date, csv_source: ActivitySource,
                       api_source: ActivitySource | None, last_csv_day: date = config.CSV_LAST_DAY) -> list[Activity]:
    """Aktivitäten im Zeitraum aus der jeweils zuständigen Quelle."""
    acts: list[Activity] = []
    if oldest <= last_csv_day:
        acts += csv_source.activities(oldest, min(newest, last_csv_day))
    if newest > last_csv_day:
        if api_source is None:
            raise ValueError(f"Für Tage nach dem {last_csv_day.isoformat()} wird intervals.icu benötigt.")
        acts += api_source.activities(max(oldest, last_csv_day + timedelta(days=1)), newest)
    acts = _dedupe(acts)
    acts.sort(key=lambda a: (a.date, a.time or time.min))
    return acts


def week_load_average(acts: list[Activity], day: date, window_days: int = config.WEEK_WINDOW_DAYS) -> float | None:
    """Ø Trainingslast pro Trainingstag in den `window_days` Tagen vor `day` (heute ausgeschlossen).

    None, wenn weniger als rules.HIGH_LOAD_MIN_TRAINING_DAYS Trainingstage mit Last > 0 vorliegen.
    """
    start = day - timedelta(days=window_days)
    per_day: dict[date, float] = defaultdict(float)
    for a in acts:
        if start <= a.date < day and a.training_load:
            per_day[a.date] += a.training_load
    days = [v for v in per_day.values() if v > 0]
    if len(days) < R.HIGH_LOAD_MIN_TRAINING_DAYS:
        return None
    return round(sum(days) / len(days), 1)


def build_day_context(day: date, csv_source, api_source: ActivitySource | None,
                      last_csv_day: date = config.CSV_LAST_DAY,
                      window_days: int = config.WEEK_WINDOW_DAYS) -> DayContext:
    """Trainings von `day` plus Wochenfenster davor; ohne Klassifikation (die macht pipeline/daytype)."""
    oldest = day - timedelta(days=window_days)
    acts = collect_activities(oldest, day, csv_source, api_source, last_csv_day)
    daily: DailySummary | None = None
    if day <= last_csv_day and hasattr(csv_source, "daily"):
        daily = csv_source.daily(day)
    return DayContext(
        date=day,
        activities=[a for a in acts if a.date == day],
        daily=daily,
        week_load_avg_7d=week_load_average(acts, day, window_days),
    )
