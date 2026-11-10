"""Phase 2, Schritt 2: API mit FastAPI TestClient, Mock-Bridge und Dry-Run (kein Netz, kein Guthaben).

Ablauf: Start → Events (live, verspätet, Wiederaufnahme per Last-Event-ID) → Ergebnis → shop → Checkliste (Konfliktregel)
→ Verlauf (cooked, rating, 422) → usage; zweiter Start → 409; „Neustart“ (neue App-Instanz) liefert dasselbe Ergebnis.
Fehler aus Phase 1 kommen als JSON mit deutschem Text, ohne Stacktrace, Keys oder Pfade.
"""

from __future__ import annotations

import io
import json
import re
import threading
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fuelplan import config
from fuelplan.api.app import create_app, get_today
from fuelplan.grocery.mock import MockBridge
from fuelplan.llm.client import CreditsExhausted
from fuelplan.pipeline import STEPS, Pipeline
from fuelplan.training import TrainingDataError
from tests.test_pipeline_mock import csv_source  # noqa: F401 – Fixture

TODAY = date(2026, 11, 3)
RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}(_\d+)?$")


class Env:
    """Pipeline-Fabrik für die App: Mock + Dry-Run, Fixture-CSV, steuerbare Bremse (gate) und Fehler."""

    def __init__(self, tmp_path, csv):
        self.tmp, self.csv = tmp_path, csv
        self.gate = threading.Event()
        self.gate.set()
        self.llm = None
        self.stderr = io.StringIO()

    def factory(self, **kw) -> Pipeline:
        kw.setdefault("log", lambda s: None)
        gate = self.gate

        def bridge():
            assert gate.wait(10), "Bremse nicht gelöst"
            return MockBridge()

        return Pipeline(mock=True, dry_run=True, runs_dir=self.tmp / "runs", history_path=self.tmp / "history" / "recipes.jsonl",
                        cache_path=self.tmp / "cache" / "prices.json", csv_source=self.csv, bridge_factory=bridge, llm=self.llm, **kw)

    def app(self, credits=None, web_dist=None):
        app = create_app(mock=True, dry_run=True, pipeline_factory=self.factory, runs_dir=self.tmp / "runs",
                         history_path=self.tmp / "history" / "recipes.jsonl", web_dist=web_dist or self.tmp / "kein-dist",
                         credits_fetcher=credits, stderr=self.stderr)
        app.dependency_overrides[get_today] = lambda: TODAY
        return app

    def client(self, **kw) -> TestClient:
        return TestClient(self.app(**kw))


@pytest.fixture
def env(tmp_path, csv_source):  # noqa: F811
    return Env(tmp_path, csv_source)


def read_sse(client: TestClient, url: str, headers: dict | None = None) -> tuple[list[dict], int]:
    """Alle Events eines SSE-Stroms (bis der Server ihn beendet) und Anzahl Keepalive-Kommentare."""
    events, cur, comments = [], {}, 0
    with client.stream("GET", url, headers=headers) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream"), r.text
        for line in r.iter_lines():
            if line == "":
                if cur:
                    events.append(cur)
                    cur = {}
                continue
            if line.startswith(":"):
                comments += 1
                continue
            key, _, value = line.partition(": ")
            cur[key] = json.loads(value) if key == "data" else value
    if cur:
        events.append(cur)
    return events, comments


def wait_done(client: TestClient, run_id: str) -> dict:
    import time
    for _ in range(200):
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("Lauf wird nicht fertig")


# --- Tagesanalyse ------------------------------------------------------------------------------------------

def test_day_without_llm(env):
    r = env.client().get("/api/day")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-11-03" and body["day_type_label"] == "Easy Run" and body["source"] == "Garmin-CSV"
    assert body["context"]["needs"]["kcal"] > 2000 and body["dinner_target"]["share_pct"] == 40
    assert len(body["context"]["activities"]) == 1 and body["context"]["activities"][0]["name"] == "Zürich Laufen"


# --- Kompletter Ablauf -------------------------------------------------------------------------------------

def test_full_flow_start_events_result_shop_checklist_history_usage_restart(env, monkeypatch):
    monkeypatch.setattr(config, "SSE_KEEPALIVE_S", 0.1)
    client = env.client()

    # Start, zweiter Start → 409 mit laufender run_id; Lauf hängt an der Bremse (vor Retrieve)
    env.gate.clear()
    r = client.post("/api/runs")
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert RUN_ID_RE.match(run_id) and r.json()["status"] == "running"
    r2 = client.post("/api/runs")
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "job_running" and r2.json()["error"]["run_id"] == run_id
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
    assert client.get("/api/runs/latest").json() == client.get(f"/api/runs/{run_id}").json()

    # Live-Strom: Bremse nach kurzer Zeit lösen, Events kommen bis done; Keepalive während des Wartens
    threading.Timer(0.4, env.gate.set).start()
    events, comments = read_sse(client, f"/api/runs/{run_id}/events")
    assert comments >= 1
    assert [e["id"] for e in events] == [str(i) for i in range(1, len(events) + 1)]
    assert [e["data"]["step"] for e in events if e["event"] == "step"] == list(STEPS)
    assert any(e["event"] == "log" and "Plan-Aufruf" in e["data"]["text"] for e in events)
    assert events[-1]["event"] == "done" and events[-1]["data"]["run_id"] == run_id
    assert set(events[-1]["data"]["price_per_portion_chf"]) == {"budget", "schnell", "aufwendig"}

    # Verspätet verbinden: alles nachgeliefert; Wiederaufnahme per Last-Event-ID (Header) und ?lastEventId= (Query)
    replay, _ = read_sse(client, f"/api/runs/{run_id}/events")
    assert replay == events
    tail, _ = read_sse(client, f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "3"})
    assert tail == events[3:]
    tail_q, _ = read_sse(client, f"/api/runs/{run_id}/events?lastEventId={events[-2]['id']}")
    assert tail_q == events[-1:]
    none, _ = read_sse(client, f"/api/runs/{run_id}/events", headers={"Last-Event-ID": events[-1]["id"]})
    assert none == []

    # Ergebnis
    body = wait_done(client, run_id)
    assert body["status"] == "done" and body["step"] == "done" and body["dry_run"] and body["mock"]
    assert [rec["variant"] for rec in body["recipes"]] == ["budget", "schnell", "aufwendig"]
    assert set(body["shopping"]) == {"budget", "schnell", "aufwendig"}
    assert all(sl["price_per_portion_chf"] > 0 and sl["lines"] for sl in body["shopping"].values())
    assert body["usage"] == {"calls": 2, "total_cost_usd": 0.0, "total_tokens": 0, "dry_run": True}
    assert "chosen_variant" not in body and isinstance(body["warnings"], list) and body["queries"] > 0
    assert body["day"]["date"] == "2026-11-03" and body["day"]["day_type_label"] == "Easy Run"
    assert client.get("/api/runs/latest").json()["run_id"] == run_id
    assert "sk-" not in json.dumps(body) and str(config.ROOT) not in json.dumps(body)

    # Teil B
    r = client.post(f"/api/runs/{run_id}/shop", json={"variant": "schnell"})
    assert r.status_code == 200, r.text
    shop = r.json()
    assert shop["variant"] == "schnell" and shop["shopping"]["recipe_name"].startswith("Poulet")
    assert shop["history_key"] == f"{run_id}:schnell" and shop["shopping"]["price_per_portion_chf"] == body["shopping"]["schnell"]["price_per_portion_chf"]
    assert client.get(f"/api/runs/{run_id}").json()["chosen_variant"] == "schnell"
    bad = client.post(f"/api/runs/{run_id}/shop", json={"variant": "vegan"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error" and "variant" in bad.json()["error"]["message"]

    # Checkliste: Positionen = Zutaten der Einkaufsliste
    cl = client.get(f"/api/runs/{run_id}/checklist").json()
    ingredients = [l["ingredient"] for l in shop["shopping"]["lines"]]
    assert cl["variant"] == "schnell" and [i["ingredient"] for i in cl["items"]] == ingredients
    assert cl["checked_count"] == 0 and cl["total"] == len(ingredients) == 7 and not any(i["checked"] for i in cl["items"])
    a, b = ingredients[0], ingredients[1]
    cl = client.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": a, "checked": True}]}).json()
    assert cl["checked_count"] == 1 and cl["items"][0]["checked"] and cl["items"][0]["changed_at"]
    assert client.get(f"/api/runs/{run_id}/checklist").json() == cl  # gespeichert (checklist.json)
    unknown = client.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": "Kaviar", "checked": True}]})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_item" and "Kaviar" in unknown.json()["error"]["message"]
    # Konfliktregel: neuer gewinnt, gleich → abgehakt gewinnt
    t1 = datetime(2026, 11, 3, 18, 0, tzinfo=config.TZ)
    state = lambda: {i["ingredient"]: i for i in client.get(f"/api/runs/{run_id}/checklist").json()["items"]}[b]  # noqa: E731
    client.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": b, "checked": True, "changed_at": t1.isoformat()}]})
    client.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": b, "checked": False, "changed_at": (t1 - timedelta(minutes=5)).isoformat()}]})
    assert state()["checked"] is True  # älteres „nicht abgehakt“ verliert
    client.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": b, "checked": False, "changed_at": (t1 + timedelta(minutes=5)).isoformat()}]})
    assert state()["checked"] is False  # neueres „nicht abgehakt“ gewinnt
    t2 = t1 + timedelta(minutes=5)
    client.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": b, "checked": True, "changed_at": t2.isoformat()}]})
    assert state()["checked"] is True  # gleicher Zeitstempel → abgehakt gewinnt
    client.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": b, "checked": False}]})
    assert state()["checked"] is False  # ohne Zeitstempel = jetzt → neuer als t2
    assert client.get(f"/api/runs/{run_id}/checklist").json()["checked_count"] == 1
    # andere Variante wählen → Checkliste beginnt leer
    assert client.post(f"/api/runs/{run_id}/shop", json={"variant": "budget"}).status_code == 200
    cl = client.get(f"/api/runs/{run_id}/checklist").json()
    assert cl["variant"] == "budget" and cl["checked_count"] == 0 and cl["total"] == len(body["shopping"]["budget"]["lines"])

    # Verlauf
    hist = client.get("/api/history").json()
    keys = [h["key"] for h in hist]
    assert f"{run_id}:schnell" in keys and f"{run_id}:budget" in keys
    assert all(h["record"]["dry_run"] for h in hist) and all(h["record"]["date"] == "2026-11-03" for h in hist)
    key = f"{run_id}:schnell"
    r = client.patch(f"/api/history/{key}", json={"cooked": True, "rating": 5})
    assert r.status_code == 200 and r.json()["record"]["cooked"] is True and r.json()["record"]["rating"] == 5
    assert [h for h in client.get("/api/history").json() if h["key"] == key][0]["record"]["rating"] == 5
    assert client.patch(f"/api/history/{key}", json={"rating": 7}).status_code == 422
    assert client.patch(f"/api/history/{key}", json={"rating": 0}).status_code == 422
    assert client.patch(f"/api/history/{key}", json={}).status_code == 422
    assert client.patch(f"/api/history/{run_id}:aufwendig", json={"cooked": True}).status_code == 404

    # Kosten
    u = client.get("/api/usage").json()
    assert u["month"] == "2026-11" and u["summary"]["calls"] == 0 and u["credits"] is None and "Dry-Run" in u["credits_note"]
    assert u["summary"]["budget_usd"] == config.MONTHLY_BUDGET_USD

    # „Neustart“: neue App-Instanz ohne Job-Puffer – Ergebnis aus dem Run-Ordner ist dasselbe
    fresh = env.client()
    assert fresh.get(f"/api/runs/{run_id}").json() == client.get(f"/api/runs/{run_id}").json()
    assert fresh.get("/api/runs/latest").json()["run_id"] == run_id
    assert fresh.get(f"/api/runs/{run_id}/checklist").json() == client.get(f"/api/runs/{run_id}/checklist").json()
    replayed, _ = read_sse(fresh, f"/api/runs/{run_id}/events")
    assert len(replayed) == 1 and replayed[0]["event"] == "done" and replayed[0]["data"] == {"run_id": run_id, "replayed": True}
    assert read_sse(fresh, f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "1"})[0] == []
    run_dir = env.tmp / "runs" / run_id
    assert (run_dir / "shop.json").exists() and not (run_dir / "checklist.json").exists()  # Wechsel auf budget hat zurückgesetzt
    fresh.patch(f"/api/runs/{run_id}/checklist", json={"items": [{"ingredient": body["shopping"]["budget"]["lines"][0]["ingredient"], "checked": True}]})
    assert json.loads((run_dir / "checklist.json").read_text(encoding="utf-8"))["variant"] == "budget"


def test_usage_with_credits_fetcher(env):
    client = env.client(credits=lambda: {"limit": 15.0, "usage": 0.5, "limit_remaining": 14.5, "total_credits": 15.0, "total_usage": 0.5})
    u = client.get("/api/usage").json()
    assert u["credits"]["limit_remaining"] == 14.5 and u["credits_note"] is None

    def boom():
        raise ConnectionError("offline")

    u = env.client(credits=boom).get("/api/usage").json()
    assert u["credits"] is None and "ConnectionError" in u["credits_note"]


# --- Fehler ------------------------------------------------------------------------------------------------

def test_not_found_and_no_run_today(env):
    client = env.client()
    for bad in ("nope", "2026-11-03_0000", "2026-11-03_0000_x"):
        r = client.get(f"/api/runs/{bad}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "run_not_found", bad
    r = client.get("/api/gibt-es-nicht")  # Router-404 im selben Fehlerformat
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.delete("/api/history")
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"
    r = client.get("/api/runs/latest")
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_run_today"
    assert client.get("/api/runs/2026-11-03_0000/checklist").status_code == 404
    assert client.post("/api/runs/2026-11-03_0000/shop", json={"variant": "budget"}).status_code == 404
    assert client.get("/api/runs/2026-11-03_0000/events").status_code == 404
    assert not (env.tmp / "runs" / "2026-11-03_0000").exists()  # nichts angelegt


def test_job_error_is_json_without_secrets_and_survives_restart(env):
    class FailingLLM:
        def complete_json(self, **kw):
            raise CreditsExhausted(f"OpenRouter: Guthaben leer (402). key=sk-or-v1-abcdef123456 pfad={config.ROOT}/.env")

    env.llm = FailingLLM()
    client = env.client()
    run_id = client.post("/api/runs").json()["run_id"]
    body = wait_done(client, run_id)
    assert body["status"] == "error" and body["error"]["code"] == "credits_exhausted"
    assert "Guthaben" in body["error"]["message"] and body["step"] == "plan"
    text = json.dumps(body)
    assert "sk-or" not in text and str(config.ROOT) not in text and "/Users" not in text and "Traceback" not in text
    assert "***" in body["error"]["detail"] and "<repo>" in body["error"]["detail"]
    events, _ = read_sse(client, f"/api/runs/{run_id}/events")
    assert events[-1]["event"] == "error" and events[-1]["data"]["code"] == "credits_exhausted" and events[-1]["data"]["status"] == 402
    assert client.get("/api/runs/latest").json()["status"] == "error"
    assert client.post("/api/runs").status_code == 202  # nach einem Fehler ist ein neuer Start möglich
    assert "Abbruch" in env.stderr.getvalue() and "sk-or" not in env.stderr.getvalue().replace("sk-or-v1-abcdef123456", "")  # Meldung im Terminal
    # Neustart: error.json im Run-Ordner
    fresh = env.client()
    again = fresh.get(f"/api/runs/{run_id}").json()
    assert again["status"] == "error" and again["error"]["code"] == "credits_exhausted"
    replayed, _ = read_sse(fresh, f"/api/runs/{run_id}/events")
    assert replayed[0]["event"] == "error" and replayed[0]["data"]["code"] == "credits_exhausted"


def test_day_errors_are_translated(env):
    class NoData:
        def activities(self, oldest, newest):
            raise TrainingDataError("intervals.icu antwortet nicht (Timeout nach 20 s).")

        def daily(self, oldest, newest):
            return []

    env.csv = NoData()
    r = env.client().get("/api/day")
    assert r.status_code == 503 and r.json()["error"]["code"] == "training_unavailable"
    assert "intervals.icu" in r.json()["error"]["message"] and "Timeout" in r.json()["error"]["detail"]

    class Broken:
        def activities(self, oldest, newest):
            return 1 / 0

        def daily(self, oldest, newest):
            return []

    env.csv = Broken()
    r = env.client().get("/api/day")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert "ZeroDivisionError" not in r.text and "ZeroDivisionError" in env.stderr.getvalue()  # Details nur im Terminal


def test_run_before_step_10_and_incomplete_run(env):
    client = env.client()
    run_id = client.post("/api/runs").json()["run_id"]
    wait_done(client, run_id)
    fresh = env.client()
    (env.tmp / "runs" / run_id / "execute_response.json").unlink()
    r = fresh.get(f"/api/runs/{run_id}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_outdated" and "Schritt 10" in r.json()["error"]["message"]
    r = fresh.post(f"/api/runs/{run_id}/shop", json={"variant": "budget"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_outdated"
    (env.tmp / "runs" / run_id / "plan_response.json").unlink()
    body = fresh.get(f"/api/runs/{run_id}").json()
    assert body["status"] == "incomplete" and body["error"]["code"] == "incomplete"
    assert fresh.get("/api/runs/latest").status_code == 404  # unvollständige Läufe zählen nicht


# --- serve / Frontend ---------------------------------------------------------------------------------------

def test_serve_binds_only_to_localhost(monkeypatch):
    import uvicorn

    from fuelplan.__main__ import main

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    assert main(["serve", "--mock", "--dry-run", "--port", "8123"]) == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8123
    with pytest.raises(SystemExit):
        main(["serve", "--host", "0.0.0.0"])  # es gibt keinen --host


def test_root_serves_web_dist_only_if_present(env, tmp_path):
    r = env.client().get("/")
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_frontend"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>FuelPlan</title>", encoding="utf-8")
    client = env.client(web_dist=dist)
    assert client.get("/").status_code == 200 and "FuelPlan" in client.get("/").text
    assert client.get("/api/runs/latest").status_code == 404  # API hat Vorrang vor der Auslieferung


# --- Block 3: Summen pro Laden (Abweichung 3.1) -----------------------------------------------------------

def test_shopping_lists_carry_store_totals(env):
    client = env.client()
    run_id = client.post("/api/runs").json()["run_id"]
    body = wait_done(client, run_id)
    assert body["status"] == "done"
    for variant, sl in body["shopping"].items():
        expected: dict[str, float] = {}
        for line in sl["lines"]:
            if line.get("product") is not None:  # exclude_none: Zeilen ohne Produkt haben kein Feld "product"
                expected[line["product"]["chain"]] = round(expected.get(line["product"]["chain"], 0.0) + line["total_chf"], 2)
        assert sl["store_totals"] == expected, variant
        assert set(sl["store_has_estimates"]) == set(expected)
        assert round(sum(sl["store_totals"].values()), 2) == round(sl["total_chf"], 2)
    shop = client.post(f"/api/runs/{run_id}/shop", json={"variant": "budget"}).json()
    assert shop["shopping"]["store_totals"] == body["shopping"]["budget"]["store_totals"]
