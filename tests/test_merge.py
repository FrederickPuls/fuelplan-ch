"""Stichtag-Logik, Duplikate, Wochenschnitt, CSV- und API-Abbildung, Fehlerfall."""

from __future__ import annotations

from datetime import date, time

import httpx
import pytest

from fuelplan.models import Activity, ActivityType, Source
from fuelplan.nutrition import rules as R
from fuelplan.training import TrainingDataError
from fuelplan.training.garmin_csv import GarminCsvSource, read_activities, read_daily
from fuelplan.training.intervals import IntervalsSource, map_activity
from fuelplan.training.merge import build_day_context, collect_activities, week_load_average

CUTOFF = date(2026, 11, 4)


def act(d: date, type=ActivityType.RUNNING, km=7.0, mins=45.0, load=100.0, source=Source.GARMIN_CSV, ext=None, name="Lauf"):
    return Activity(date=d, type=type, name=name, duration_min=mins, distance_km=km, training_load=load, source=source, external_id=ext)


class FakeSource:
    def __init__(self, acts, fail=False):
        self._acts = acts
        self.calls: list[tuple[date, date]] = []
        self.fail = fail

    def activities(self, oldest, newest):
        self.calls.append((oldest, newest))
        if self.fail:
            raise TrainingDataError("intervals.icu nicht erreichbar")
        return [a for a in self._acts if oldest <= a.date <= newest]

    def daily(self, day):
        return None


# --- Stichtag ------------------------------------------------------------------------

def test_day_before_cutoff_uses_csv_only_and_never_calls_api():
    csv = FakeSource([act(date(2026, 11, 3)), act(date(2026, 11, 1), km=12.5)])
    api = FakeSource([act(date(2026, 11, 3), source=Source.INTERVALS, ext="x")])
    ctx = build_day_context(date(2026, 11, 3), csv, api, last_csv_day=CUTOFF)
    assert api.calls == []
    assert [a.source for a in ctx.activities] == [Source.GARMIN_CSV]
    assert csv.calls == [(date(2026, 10, 27), date(2026, 11, 3))]


def test_day_on_cutoff_uses_csv_only():
    csv = FakeSource([act(CUTOFF)])
    api = FakeSource([])
    ctx = build_day_context(CUTOFF, csv, api, last_csv_day=CUTOFF)
    assert api.calls == [] and len(ctx.activities) == 1


def test_day_after_cutoff_uses_api_for_today_and_csv_for_earlier_days():
    csv = FakeSource([act(date(2026, 11, 3), load=60), act(date(2026, 11, 1), load=115), act(date(2026, 11, 5), load=999)])
    api = FakeSource([act(date(2026, 11, 5), source=Source.INTERVALS, ext="i1", load=80), act(date(2026, 11, 2), source=Source.INTERVALS, ext="i0")])
    ctx = build_day_context(date(2026, 11, 6), csv, api, last_csv_day=CUTOFF)
    assert csv.calls == [(date(2026, 10, 30), CUTOFF)]
    assert api.calls == [(date(2026, 11, 5), date(2026, 11, 6))]
    assert ctx.activities == []  # heute (06.11.) nichts
    # Wochenschnitt über den Stichtag: 01.11. (115) + 03.11. (60) aus CSV, 05.11. (80) aus API → (115+60+80)/3
    assert ctx.week_load_avg_7d == round((115 + 60 + 80) / 3, 1)


def test_api_required_after_cutoff():
    with pytest.raises(ValueError):
        collect_activities(date(2026, 11, 1), date(2026, 11, 6), FakeSource([]), None, last_csv_day=CUTOFF)


def test_api_error_aborts_cleanly():
    with pytest.raises(TrainingDataError):
        build_day_context(date(2026, 11, 6), FakeSource([]), FakeSource([], fail=True), last_csv_day=CUTOFF)


# --- Duplikate ----------------------------------------------------------------------------

def test_duplicates_removed_by_external_id_and_by_key():
    d = date(2026, 11, 6)
    api = FakeSource([
        act(d, source=Source.INTERVALS, ext="i1", km=7.0, mins=45.0),
        act(d, source=Source.INTERVALS, ext="i1", km=7.0, mins=45.0),  # gleiche ID
        act(d, source=Source.INTERVALS, ext="i2", km=7.02, mins=45.4),  # gleicher Schlüssel (gerundet)
        act(d, source=Source.INTERVALS, ext="i3", km=5.0, mins=30.0),  # anders
    ])
    acts = collect_activities(d, d, FakeSource([]), api, last_csv_day=CUTOFF)
    assert [a.external_id for a in acts] == ["i1", "i3"]


def test_activities_sorted_by_date_and_time():
    d = date(2026, 11, 6)
    a1 = act(d, ext="a", km=5.0, mins=30.0, source=Source.INTERVALS).model_copy(update={"time": time(18, 0)})
    a2 = act(d, ext="b", km=7.0, mins=45.0, source=Source.INTERVALS).model_copy(update={"time": time(7, 0)})
    a3 = act(d, type=ActivityType.STRENGTH, km=0, mins=60, ext="c", source=Source.INTERVALS)  # ohne Zeit → zuerst
    acts = collect_activities(d, d, FakeSource([]), FakeSource([a1, a2, a3]), last_csv_day=CUTOFF)
    assert [a.external_id for a in acts] == ["c", "b", "a"]


# --- Wochenschnitt -------------------------------------------------------------------------

def test_week_average_excludes_today_and_days_outside_window():
    day = date(2026, 11, 10)
    acts = [
        act(day, load=500),  # heute: nicht im Schnitt
        act(day - __import__("datetime").timedelta(days=1), load=100),
        act(day - __import__("datetime").timedelta(days=3), load=50),
        act(day - __import__("datetime").timedelta(days=3), type=ActivityType.STRENGTH, km=0, load=10),  # gleicher Tag → summiert
        act(day - __import__("datetime").timedelta(days=8), load=999),  # ausserhalb
    ]
    assert week_load_average(acts, day) == round((100 + 60) / 2, 1)


def test_week_average_none_with_too_few_training_days():
    day = date(2026, 11, 10)
    acts = [act(day - __import__("datetime").timedelta(days=1), load=100)]
    assert R.HIGH_LOAD_MIN_TRAINING_DAYS >= 2
    assert week_load_average(acts, day) is None
    assert week_load_average([], day) is None


# --- CSV ---------------------------------------------------------------------------------------

def test_csv_reader_maps_types_and_respects_cutoff(tmp_path):
    p = tmp_path / "acts.csv"
    p.write_text(
        "date,time,type,name,duration_min,distance_km,avg_hr,max_hr,kcal,training_load,aerobic_te,anaerobic_te,te_label,z1_min,z2_min,z3_min,z4_min,z5_min\n"
        "2026-11-03,18:05,running,Zürich Laufen,40.0,6.2,148.0,168.0,455.0,62.0,3.0,0.0,AEROBIC_BASE,1,2,3,4,5\n"
        "2026-11-04,10:00,strength_training,Krafttraining,55.0,0.0,115.0,,310.0,14.0,,,UNKNOWN,,,,,\n"
        "2026-11-05,10:00,other,Surfen,20.0,3.0,,,80.0,3.0,,,UNKNOWN,,,,,\n"
    )
    acts = read_activities(p, last_day=CUTOFF)
    assert len(acts) == 2  # 05.11. liegt nach dem Stichtag
    assert acts[0].type is ActivityType.RUNNING and acts[0].time == time(18, 5) and acts[0].te_label == "AEROBIC_BASE"
    assert acts[1].type is ActivityType.STRENGTH and acts[1].max_hr is None and acts[1].source is Source.GARMIN_CSV
    src = GarminCsvSource(p, tmp_path / "missing_daily.csv", last_day=CUTOFF)
    assert len(src.activities(date(2026, 11, 4), date(2026, 11, 4))) == 1
    assert src.daily(CUTOFF) is None


def test_daily_reader(tmp_path):
    p = tmp_path / "daily.csv"
    p.write_text("date,total_kcal,active_kcal,bmr_kcal,steps,resting_hr,avg_stress,bb_charged,bb_drained\n2026-11-03,2800.0,1000.0,1800.0,12000,52,30,80,70\n2026-11-04,2000.0,0.0,1800.0,,,-1,,\n")
    daily = read_daily(p, last_day=CUTOFF)
    assert daily[date(2026, 11, 3)].steps == 12000 and daily[date(2026, 11, 3)].resting_hr == 52
    assert daily[CUTOFF].steps is None


def test_missing_csv_raises(tmp_path):
    with pytest.raises(TrainingDataError):
        read_activities(tmp_path / "nope.csv")


# --- intervals.icu ----------------------------------------------------------------------------

SAMPLE = {
    "id": "i123", "start_date_local": "2026-11-05T18:30:00", "type": "Run", "name": "Zürich - Intervalle 6 x 1 km",
    "distance": 8100.0, "moving_time": 2580, "elapsed_time": 2700, "average_heartrate": 158.0, "max_heartrate": 179.0,
    "calories": 560, "icu_training_load": 150,
}


def test_map_activity_from_api():
    a = map_activity(SAMPLE)
    assert a.date == date(2026, 11, 5) and a.time == time(18, 30)
    assert a.type is ActivityType.RUNNING and a.distance_km == 8.1 and a.duration_min == 43.0
    assert a.avg_hr == 158.0 and a.kcal == 560 and a.training_load == 150
    assert a.source is Source.INTERVALS and a.external_id == "i123" and a.te_label is None


@pytest.mark.parametrize("t,expected", [("WeightTraining", ActivityType.STRENGTH), ("Other", ActivityType.OTHER),
                                        ("Hike", ActivityType.HIKING), ("Ride", ActivityType.CYCLING), ("Swim", ActivityType.UNKNOWN)])
def test_map_activity_types(t, expected):
    assert map_activity({**SAMPLE, "type": t}).type is expected


def _source(handler):
    return IntervalsSource(api_key="test-key", athlete_id="i0", transport=httpx.MockTransport(handler))


def test_intervals_source_get_only_with_basic_auth():
    seen = {}

    def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=[SAMPLE])

    acts = _source(handler).activities(date(2026, 11, 5), date(2026, 11, 6))
    assert seen["method"] == "GET"
    assert "/athlete/i0/activities?oldest=2026-11-05&newest=2026-11-06" in seen["url"]
    assert seen["auth"].startswith("Basic ")
    assert len(acts) == 1 and acts[0].external_id == "i123"


@pytest.mark.parametrize("status,needle", [(401, "lehnt"), (429, "Rate-Limit"), (500, "Fehler 500")])
def test_intervals_source_errors(status, needle):
    with pytest.raises(TrainingDataError, match=needle):
        _source(lambda r: httpx.Response(status, text="x")).activities(date(2026, 11, 5), date(2026, 11, 5))


def test_intervals_source_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    with pytest.raises(TrainingDataError, match="Timeout"):
        _source(handler).activities(date(2026, 11, 5), date(2026, 11, 5))
