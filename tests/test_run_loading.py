"""Phase 2, Schritt 1: Fortschritts-Events (on_step), Laden eines Run-Ordners als Datenobjekte, RunDir.find/latest."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from fuelplan.pipeline import STEPS, Pipeline
from fuelplan.runlog import RunDir
from tests.test_pipeline_mock import _NoBridge, _NoLLM, csv_source  # noqa: F401 – Fixture


@pytest.fixture
def make_pipe(tmp_path, csv_source):  # noqa: F811
    def _make(**kw):
        kw.setdefault("log", lambda s: None)
        return Pipeline(mock=True, dry_run=True, runs_dir=tmp_path / "runs", history_path=tmp_path / "history" / "recipes.jsonl",
                        cache_path=tmp_path / "cache" / "prices.json", csv_source=csv_source, **kw)
    return _make


def test_on_step_reports_fixed_steps_in_order_and_log_unchanged(make_pipe):
    steps, logs = [], []
    pipe = make_pipe(on_step=lambda s, d: steps.append((s, d)), log=logs.append)
    a = pipe.part_a(date(2026, 11, 3))
    assert [s for s, _ in steps] == list(STEPS) == ["collect", "plan", "retrieve", "execute", "compute", "done"]
    assert steps[0][1].endswith("2026-11-03") and "dry-run" in steps[1][1] and "Mock" in steps[2][1] and steps[-1][1] == a.run.name
    assert logs == ["Plan-Aufruf (dry-run) …", "Produkte für alle drei Varianten (24 Zutaten, Mock) …",
                    "Execute-Aufruf für alle drei Varianten (dry-run) …"]  # CLI-Text unverändert


def test_on_step_is_optional(make_pipe):
    assert make_pipe().part_a(date(2026, 11, 3)).run.has("plan_response.json")


def test_load_part_a_rebuilds_same_result_after_restart(make_pipe):
    pipe = make_pipe()
    a = pipe.part_a(date(2026, 11, 3))
    assert a.usage["total_cost_usd"] == 0 and [c["label"] for c in a.usage["calls"]] == ["plan", "execute"]
    assert a.chosen_variant is None
    # „Neustart“: neue Pipeline, nur der Ordner ist noch da; Teil A darf dabei weder Bridge noch LLM brauchen
    fresh = make_pipe(bridge_factory=_NoBridge(), llm=_NoLLM())
    loaded = fresh.load_part_a(RunDir.find(a.run.name, pipe.runs_dir))
    assert loaded.plan == a.plan and loaded.ctx == a.ctx and loaded.output == a.output
    assert loaded.warnings == a.warnings and loaded.queries == a.queries and loaded.usage == a.usage
    assert set(loaded.shopping) == {"budget", "schnell", "aufwendig"}
    for v in loaded.shopping:
        assert loaded.shopping[v] == a.shopping[v]
    assert loaded.chosen_variant is None
    # nach Teil B: gewählte Variante aus shop.json
    pipe.part_b("schnell", a.run)
    sj = a.run.read_json("shop.json")
    assert sj["variant"] == "schnell" and sj["history_key"] == f"{a.run.name}:schnell" and sj["recipe_name"].startswith("Poulet")
    assert fresh.load_part_a(a.run).chosen_variant == "schnell"
    # ältere Läufe ohne shop.json: Variante aus dem Archiv
    (a.run.path / "shop.json").unlink()
    assert fresh.load_part_a(a.run).chosen_variant == "schnell"


def test_load_run_rejects_incomplete_or_pre_step_10(make_pipe):
    pipe = make_pipe()
    a = pipe.part_a(date(2026, 11, 3))
    (a.run.path / "execute_response.json").unlink()
    with pytest.raises(RuntimeError, match="vor Schritt 10"):
        pipe.load_part_a(a.run)
    (a.run.path / "plan_response.json").unlink()
    with pytest.raises(RuntimeError, match="kein Plan"):
        pipe.load_part_a(a.run)


def test_part_b_uses_shared_loader_and_still_writes_history(make_pipe):
    pipe = make_pipe()
    a = pipe.part_a(date(2026, 11, 3))
    b = pipe.part_b("budget", a.run)
    assert b.shopping.variant == "budget" and a.run.has("output_b.md") and a.run.read_json("shop.json")["variant"] == "budget"
    with pytest.raises(RuntimeError, match="Unbekannte Variante"):
        pipe.part_b("vegan", a.run)


def test_run_dir_find_validates_name_and_never_creates(tmp_path):
    r = RunDir.create(tmp_path, now=datetime(2026, 11, 8, 9, 0))
    assert RunDir.find(r.name, tmp_path).path == r.path
    for bad in ("", "../etc", "2026-11-08", "2026-11-08_0900/x", "foo", "2026-11-08_0901"):
        assert RunDir.find(bad, tmp_path) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == [r.name]  # find hat nichts angelegt


def test_latest_with_plan_filters_by_day_from_day_context(tmp_path):
    r1 = RunDir.create(tmp_path, now=datetime(2026, 11, 8, 9, 0))
    r2 = RunDir.create(tmp_path, now=datetime(2026, 11, 8, 10, 0))
    r3 = RunDir.create(tmp_path, now=datetime(2026, 11, 8, 11, 0))
    for r, d in ((r1, "2026-11-08"), (r2, "2026-11-03"), (r3, "2026-11-08")):
        r.write_json("plan_response.json", {})
        r.write_json("day_context.json", {"date": d})
    (r3.path / "plan_response.json").unlink()  # unvollständig
    assert r1.day() == date(2026, 11, 8) and r3.usage() == {"calls": [], "total_cost_usd": 0.0, "total_tokens": 0}
    assert [r.name for r in RunDir.list_with_plan(tmp_path)] == [r1.name, r2.name]
    assert RunDir.latest_with_plan(tmp_path).name == r2.name
    assert RunDir.latest_with_plan(tmp_path, day=date(2026, 11, 8)).name == r1.name
    assert RunDir.latest_with_plan(tmp_path, day=date(2026, 11, 9)) is None
