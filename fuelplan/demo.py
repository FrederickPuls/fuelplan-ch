"""Demo-Modus: die App ohne API-Keys und ohne eigene Trainingsdaten ausprobieren.

`python -m fuelplan demo` startet dieselbe API wie `serve --mock --dry-run`, nimmt die Trainings aber aus einer
erfundenen Woche statt aus intervals.icu oder dem Garmin-Export. Supermarkt = Mock-Bridge, Modell = gespeicherte
Antworten aus tests/fixtures/llm/. Läufe, Archiv und Preis-Cache landen in einem eigenen Ordner (Standard: temporär),
nie in runs/ oder history/. Kein Netz, kein Guthaben, nichts aus .env.

Die Demo-Woche hängt am heutigen Datum: heute ein Intervall-Lauf, davor Kraft, lockere Läufe und ein Long Run.
Alle Werte sind erfunden.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import date, time, timedelta
from pathlib import Path

from fastapi import FastAPI

from fuelplan import config
from fuelplan.models import Activity, ActivityType, Source
from fuelplan.pipeline import Pipeline

# (Tage vor heute, Uhrzeit, Typ, Name, Dauer min, Distanz km, Ø-Puls, Max-Puls, kcal, Trainingslast)
DEMO_WEEK: tuple[tuple, ...] = (
    (0, time(17, 30), ActivityType.RUNNING, "Intervalle 5 x 1 km", 48.0, 8.4, 159.0, 181.0, 590.0, 150.0),
    (1, time(18, 0), ActivityType.STRENGTH, "Krafttraining", 60.0, 0.0, 112.0, 148.0, 330.0, 16.0),
    (2, time(7, 15), ActivityType.RUNNING, "Lockerer Lauf", 40.0, 6.2, 148.0, 168.0, 455.0, 62.0),
    (4, time(9, 30), ActivityType.RUNNING, "Long Run", 92.0, 16.2, 154.0, 170.0, 1120.0, 180.0),
    (5, time(18, 15), ActivityType.STRENGTH, "Krafttraining", 55.0, 0.0, 115.0, 150.0, 310.0, 14.0),
    (6, time(17, 45), ActivityType.RUNNING, "Lockerer Lauf", 45.0, 7.0, 146.0, 165.0, 500.0, 70.0),
)


class DemoSource:
    """ActivitySource mit der erfundenen Woche aus DEMO_WEEK, verankert an `today()`."""

    def __init__(self, today: Callable[[], date] = config.today) -> None:
        self._today = today

    def activities(self, oldest: date, newest: date) -> list[Activity]:
        anchor = self._today()
        out: list[Activity] = []
        for days_ago, at, type_, name, minutes, km, avg_hr, max_hr, kcal, load in DEMO_WEEK:
            day = anchor - timedelta(days=days_ago)
            if oldest <= day <= newest:
                out.append(Activity(date=day, time=at, type=type_, name=name, duration_min=minutes, distance_km=km, avg_hr=avg_hr,
                                    max_hr=max_hr, kcal=kcal, training_load=load, source=Source.INTERVALS,
                                    external_id=f"demo-{day.isoformat()}-{days_ago}"))
        return out


def create_demo_app(data_dir: Path | None = None, today: Callable[[], date] = config.today, web_dist: Path | None = None) -> FastAPI:
    """FastAPI-App im Demo-Modus. `data_dir` nimmt runs/, history/ und cache/ auf (Standard: neuer temporärer Ordner)."""
    from fuelplan.api.app import create_app, get_today

    data_dir = Path(data_dir) if data_dir else Path(tempfile.mkdtemp(prefix="fuelplan-demo-"))
    runs_dir = data_dir / "runs"
    history_path = data_dir / "history" / "recipes.jsonl"
    source = DemoSource(today)

    def pipeline_factory(**kw) -> Pipeline:
        # Dieselbe Quelle für beide Seiten des Stichtags: die Demo fragt nie intervals.icu ab und liest keine CSV.
        return Pipeline(mock=True, dry_run=True, runs_dir=runs_dir, history_path=history_path,
                        cache_path=data_dir / "cache" / "price_cache_mock.json", csv_source=source,
                        api_source_factory=lambda: source, **kw)

    app = create_app(mock=True, dry_run=True, pipeline_factory=pipeline_factory, runs_dir=runs_dir, history_path=history_path,
                     web_dist=web_dist)
    app.dependency_overrides[get_today] = today
    app.state.demo_data_dir = data_dir
    return app
