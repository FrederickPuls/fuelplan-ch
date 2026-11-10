"""Demo-Modus: erfundene Trainingswoche, Mock-Bridge und Dry-Run – ohne .env, ohne data/, ohne Netz."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from fuelplan.demo import DEMO_WEEK, DemoSource, create_demo_app
from tests.test_api import wait_done

TODAY = date(2027, 2, 9)  # beliebiger Tag nach dem CSV-Stichtag


def test_demo_source_is_anchored_at_today():
    src = DemoSource(lambda: TODAY)
    week = src.activities(TODAY - timedelta(days=7), TODAY)
    assert len(week) == len(DEMO_WEEK)
    today = src.activities(TODAY, TODAY)
    assert [a.name for a in today] == ["Intervalle 5 x 1 km"] and today[0].date == TODAY


def test_demo_app_runs_full_flow_without_keys(tmp_path, monkeypatch):
    for name in ("INTERVALS_API_KEY", "INTERVALS_ATHLETE_ID", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    app = create_demo_app(data_dir=tmp_path, today=lambda: TODAY, web_dist=tmp_path / "kein-dist")
    client = TestClient(app)

    day = client.get("/api/day").json()
    assert day["date"] == TODAY.isoformat() and day["day_type_label"] == "Intensiv"
    assert day["context"]["week_load_avg_7d"] and len(day["context"]["activities"]) == 1

    started = client.post("/api/runs")
    assert started.status_code == 202, started.text
    result = wait_done(client, started.json()["run_id"])
    assert result["status"] == "done" and len(result["recipes"]) == 3 and result["mock"] and result["dry_run"]
    assert (tmp_path / "runs").is_dir()  # Läufe der Demo liegen im Demo-Ordner, nicht in runs/
