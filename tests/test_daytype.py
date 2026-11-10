"""Tag-Typ: Regelfälle aus dem Plan + Beispieltage aus tests/fixtures/daytype_days.json (erfundene Werte)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fuelplan.models import Activity, ActivityType, DayContext, DayType
from fuelplan.nutrition import rules as R
from fuelplan.nutrition.daytype import classify
from tests.conftest import make_activity as A
from tests.conftest import make_day as D

FIXTURES = Path(__file__).parent / "fixtures" / "daytype_days.json"


# --- Regelfälle aus Phase1_Plan.md, Schritt 2 ----------------------------------------

def test_interval_by_name_beats_distance():
    c = classify(D(A(name="Zürich - Intervalle 4 x 2", distance_km=9.6, te_label="LACTATE_THRESHOLD")))
    assert c.day_type is DayType.INTENSIV
    assert c.macro_source is None
    assert "Intervall-Lauf" in c.reason and "Name" in c.reason


@pytest.mark.parametrize("label", ["VO2MAX", "ANAEROBIC_CAPACITY", "vo2max"])
def test_interval_by_te_label(label):
    c = classify(D(A(name="Zürich Laufen", distance_km=8.0, te_label=label)))
    assert c.day_type is DayType.INTENSIV
    assert "TE-Label" in c.reason


@pytest.mark.parametrize("label", ["TEMPO", "LACTATE_THRESHOLD"])
def test_tempo_or_threshold_alone_is_not_interval(label):
    c = classify(D(A(name="Zürich Laufen", distance_km=7.5, te_label=label, avg_hr=158)))
    assert c.day_type is DayType.EASY_RUN


def test_interval_long_distance_uses_long_run_macros():
    c = classify(D(A(name="Intervalle 10 x 1", distance_km=14.5)))
    assert c.day_type is DayType.INTENSIV
    assert c.macro_source is DayType.LONG_RUN
    assert "Long Run" in c.reason


def test_race_is_intensive():
    c = classify(D(A(name="Zürich Wettkampf 10 km", distance_km=10.0)))
    assert c.day_type is DayType.INTENSIV
    assert "Wettkampf" in c.reason


@pytest.mark.parametrize(
    "km,expected",
    [(15.0, DayType.LONG_RUN), (14.0, DayType.LONG_RUN), (13.9, DayType.LONG_RUN_LIGHT), (10.0, DayType.LONG_RUN_LIGHT),
     (9.0, DayType.LONG_RUN_LIGHT), (8.9, DayType.EASY_RUN), (6.0, DayType.EASY_RUN), (4.0, DayType.EASY_RUN),
     (3.9, DayType.LOCKER)],
)
def test_run_by_distance(km, expected):
    c = classify(D(A(distance_km=km, duration_min=km * 6)))
    assert c.day_type is expected
    assert c.components == [expected]


def test_two_runs_sum_distance():
    c = classify(D(A(distance_km=5.0, duration_min=30), A(distance_km=5.0, duration_min=30)))
    assert c.day_type is DayType.LONG_RUN_LIGHT
    assert "2 Läufe" in c.reason and "10,0 km" in c.reason


def test_strength_only():
    c = classify(D(A(type=ActivityType.STRENGTH, name="Krafttraining", duration_min=60, avg_hr=110)))
    assert c.day_type is DayType.KRAFT
    assert c.components == [DayType.KRAFT]


def test_strength_with_interval_label_stays_strength():
    c = classify(D(A(type=ActivityType.STRENGTH, name="Krafttraining", duration_min=55, te_label="ANAEROBIC_CAPACITY")))
    assert c.day_type is DayType.KRAFT


def test_surf_alone_is_locker_even_if_short():
    c = classify(D(A(type=ActivityType.OTHER, name="Wakesurfen", duration_min=12, distance_km=3.0, avg_hr=105)))
    assert c.day_type is DayType.LOCKER
    assert c.components == [DayType.LOCKER]
    assert c.surf
    assert c.label == "Locker (Surf)"
    assert "Surf-Session" in c.reason and "oberen Rand" in c.reason


def test_surf_plus_strength_is_combination():
    c = classify(D(
        A(type=ActivityType.OTHER, name="Wakesurfen", duration_min=15, distance_km=3.0),
        A(type=ActivityType.STRENGTH, name="Krafttraining", duration_min=80),
    ))
    assert c.day_type is DayType.KRAFT
    assert c.components == [DayType.KRAFT, DayType.LOCKER]
    assert c.surf
    assert c.label == "Kraft + Locker (Surf)"
    assert "Kombination" in c.reason


def test_surf_plus_long_run_is_combination():
    c = classify(D(
        A(distance_km=16.0, duration_min=90),
        A(type=ActivityType.OTHER, name="Surfen", duration_min=20, distance_km=3.0),
    ))
    assert c.components == [DayType.LONG_RUN, DayType.LOCKER]
    assert c.label == "Long Run + Locker (Surf)"


def test_surf_plus_hiking_merge_into_one_locker_component():
    c = classify(D(
        A(type=ActivityType.HIKING, name="Wandern", duration_min=100, distance_km=6),
        A(type=ActivityType.OTHER, name="Surfen", duration_min=20, distance_km=3.0),
    ))
    assert c.components == [DayType.LOCKER]
    assert "Wandern" in c.reason and "Surf-Session" in c.reason


def test_run_plus_strength_combination():
    c = classify(D(A(distance_km=5.1, duration_min=33), A(type=ActivityType.STRENGTH, name="Krafttraining", duration_min=81)))
    assert c.day_type is DayType.EASY_RUN
    assert c.components == [DayType.EASY_RUN, DayType.KRAFT]
    assert c.label == "Easy Run + Kraft"
    assert "Kombination" in c.reason


def test_no_training_is_rest_day():
    c = classify(D())
    assert c.day_type is DayType.RUHETAG
    assert c.reason == "Ruhetag, weil kein Training."


def test_short_training_is_rest_day():
    c = classify(D(A(type=ActivityType.STRENGTH, name="Krafttraining", duration_min=17)))
    assert c.day_type is DayType.RUHETAG
    assert "17 min" in c.reason


def test_high_avg_hr_upgrades_easy_run_to_intensive():
    c = classify(D(A(distance_km=5.0, avg_hr=R.HIGH_AVG_HR_BPM)))
    assert c.day_type is DayType.INTENSIV
    assert "Ø-Puls" in c.reason


def test_high_avg_hr_does_not_change_long_run():
    c = classify(D(A(distance_km=16.0, avg_hr=170)))
    assert c.day_type is DayType.LONG_RUN


def test_high_load_vs_week_upgrades_easy_run():
    avg = 50.0
    c = classify(D(A(distance_km=7.0, avg_hr=150, training_load=avg * R.HIGH_LOAD_FACTOR_VS_WEEK + 1), week_load_avg_7d=avg))
    assert c.day_type is DayType.INTENSIV
    assert "Wochenschnitt" in c.reason
    c2 = classify(D(A(distance_km=7.0, avg_hr=150, training_load=avg * R.HIGH_LOAD_FACTOR_VS_WEEK), week_load_avg_7d=avg))
    assert c2.day_type is DayType.EASY_RUN


def test_hiking_is_locker():
    c = classify(D(A(type=ActivityType.HIKING, name="Wandern", duration_min=120, distance_km=7)))
    assert c.day_type is DayType.LOCKER


def test_reason_is_one_sentence():
    for ctx in (D(), D(A(distance_km=16)), D(A(distance_km=5), A(type=ActivityType.STRENGTH, duration_min=60))):
        r = classify(ctx).reason
        assert r.endswith(".") and r.count(". ") == 0 and "weil" in r


# --- Beispieltage (Ground Truth in tests/fixtures/daytype_days.json, erfundene Werte) -----

def _load_days():
    data = json.loads(FIXTURES.read_text())
    return [pytest.param(d, id=d["date"]) for d in data["days"]]


@pytest.mark.parametrize("fx", _load_days())
def test_fixture_day(fx):
    ctx = DayContext(date=fx["date"], activities=[Activity(**a) for a in fx["activities"]])
    c = classify(ctx)
    exp = fx["expected"]
    assert c.day_type.value == exp["day_type"], c.reason
    assert [t.value for t in c.components] == exp["components"], c.reason
    assert c.reason.endswith(".") and "weil" in c.reason
