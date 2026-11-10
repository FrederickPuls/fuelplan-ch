from __future__ import annotations

import os
from datetime import date

import pytest

# Tests rechnen immer mit dem Beispielgewicht, unabhängig von der eigenen .env (muss vor dem Import von fuelplan stehen).
os.environ["FUELPLAN_WEIGHT_KG"] = "70"

from fuelplan.models import Activity, ActivityType, DayContext, Source


def make_activity(
    type: ActivityType | str = ActivityType.RUNNING,
    name: str = "Zürich Laufen",
    duration_min: float = 45.0,
    distance_km: float = 0.0,
    avg_hr: float | None = 150.0,
    te_label: str | None = "AEROBIC_BASE",
    training_load: float | None = 80.0,
    day: date = date(2026, 10, 20),
) -> Activity:
    return Activity(
        date=day, type=type, name=name, duration_min=duration_min, distance_km=distance_km,
        avg_hr=avg_hr, te_label=te_label, training_load=training_load, source=Source.GARMIN_CSV,
    )


def make_day(*activities: Activity, week_load_avg_7d: float | None = None) -> DayContext:
    return DayContext(date=date(2026, 10, 20), activities=list(activities), week_load_avg_7d=week_load_avg_7d)


@pytest.fixture
def run():
    return make_activity


@pytest.fixture
def day():
    return make_day
