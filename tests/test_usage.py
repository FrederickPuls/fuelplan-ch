"""Schritt 8: Monatsübersicht, Budget, Restguthaben (Mock), Schutz der Rohdaten."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from fuelplan import config
from fuelplan.llm.client import Usage
from fuelplan.runlog import month_summary, record_usage, render_month_summary

FX = config.ROOT / "tests" / "fixtures" / "llm"


def _log(tmp_path) -> Path:
    path = tmp_path / "llm_usage.jsonl"
    for ts, label, cost, run, src in [("2026-11-06T10:00:00", "plan", 0.03, "2026-11-06_1000", "openrouter"),
                                      ("2026-11-06T10:01:00", "execute", 0.01, "2026-11-06_1000", "openrouter"),
                                      ("2026-11-07T19:00:00", "plan", 0.02, "2026-11-07_1900", "estimate (2026-11-06)"),
                                      ("2026-10-30T19:00:00", "plan", 0.5, "2026-10-30_1900", "openrouter")]:
        u = Usage(model="m", label=label, input_tokens=100, output_tokens=50, cost_usd=cost, cost_source=src, timestamp=ts)
        record_usage(u, path, run_dir=run)
    return path


def test_month_summary_groups_by_run_and_month(tmp_path):
    path = _log(tmp_path)
    s = month_summary(2026, 11, path)
    assert s["calls"] == 3 and len(s["runs"]) == 2
    assert s["total_cost_usd"] == pytest.approx(0.06) and s["estimated_calls"] == 1
    assert s["runs"]["2026-11-06_1000"]["calls"] == 2 and s["runs"]["2026-11-06_1000"]["cost_usd"] == pytest.approx(0.04)
    assert s["budget_left_usd"] == pytest.approx(config.MONTHLY_BUDGET_USD - 0.06)
    assert month_summary(2026, 10, path)["total_cost_usd"] == pytest.approx(0.5)
    assert month_summary(2026, 9, path)["calls"] == 0


def test_render_month_summary_with_and_without_credits(tmp_path):
    s = month_summary(2026, 11, _log(tmp_path))
    text = render_month_summary(s, {"limit": 15.0, "usage": 0.1, "limit_remaining": 14.9, "total_credits": 15.0, "total_usage": 0.1})
    assert "## Kosten 11/2026" in text and "Monatsbudget" in text and "| 2026-11-06_1000 | 2 (plan, execute) |" in text
    assert "Key-Limit 15.00 USD" in text and "Rest 14.9000 USD" in text and "geschätzten Kosten" in text
    assert "nicht abgefragt" in render_month_summary(s, None)


def test_credits_uses_get_only_and_hides_key(monkeypatch):
    from fuelplan.llm import openrouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path))
        if req.url.path.endswith("/auth/key"):
            return httpx.Response(200, json={"data": {"limit": 15, "usage": 0.25, "limit_remaining": 14.75}})
        return httpx.Response(200, json={"data": {"total_credits": 15, "total_usage": 0.25}})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    c = openrouter.credits()
    assert c == {"limit": 15.0, "usage": 0.25, "limit_remaining": 14.75, "total_credits": 15.0, "total_usage": 0.25}
    assert all(m == "GET" for m, _ in seen) and "secret-key" not in json.dumps(c)


def test_only_day_summaries_go_to_the_model():
    """Die Plan-Anfrage enthält keine Roh-CSV-Zeilen oder Dateinamen, nur die Tageszusammenfassung."""
    req = json.loads((FX / "plan_request.json").read_text(encoding="utf-8"))
    text = req["system"] + req["user"]
    assert "garmin_activities" not in text and "garmin_daily" not in text and "Data_till" not in text
    assert "te_label" not in text and "z1_min" not in text and ".csv" not in text
    assert "Tagesanalyse" in req["user"] and "Tagesbedarf gesamt" in req["user"]
    exec_req = json.loads((FX / "execute_request.json").read_text(encoding="utf-8"))
    assert "INTERVALS" not in exec_req["user"] and "sk-or" not in exec_req["user"]
