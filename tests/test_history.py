"""Phase 2, Schritt 1: Archiv-Einträge adressierbar (key) und änderbar (update: cooked, rating 1–5), atomar geschrieben."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from fuelplan import history
from fuelplan.history import RecipeRecord, append, read_all, read_recent, update


def _rec(run_dir="2026-11-07_1706", variant="aufwendig", day=date(2026, 11, 7), **kw) -> RecipeRecord:
    return RecipeRecord(date=day, variant=variant, name=f"Rezept {variant}", run_dir=run_dir, **kw)


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "history" / "recipes.jsonl"
    for r in (_rec("2026-11-06_1415", "schnell", date(2026, 11, 6)), _rec(), _rec(variant="schnell"),
              _rec("2026-11-06_1409", "schnell", date(2026, 11, 3), dry_run=True)):
        append(r, p)
    return p


def test_key_is_run_dir_and_variant_or_date_fallback():
    assert _rec().key == "2026-11-07_1706:aufwendig"
    assert RecipeRecord(date=date(2026, 11, 7), variant="budget", name="x").key == "2026-11-07:budget"


def test_read_all_keeps_file_order_and_dry_run(path):
    recs = read_all(path)
    assert [r.key for r in recs] == ["2026-11-06_1415:schnell", "2026-11-07_1706:aufwendig", "2026-11-07_1706:schnell", "2026-11-06_1409:schnell"]
    assert recs[-1].dry_run and read_all(path.with_name("nix.jsonl")) == []
    assert [r.key for r in read_recent(today=date(2026, 11, 7), path=path)] == ["2026-11-07_1706:aufwendig", "2026-11-07_1706:schnell", "2026-11-06_1415:schnell"]


def test_update_cooked_and_rating_only_touches_matching_entry(path):
    before = path.read_text(encoding="utf-8").splitlines()
    changed = update("2026-11-07_1706:aufwendig", cooked=True, rating=4, path=path)
    assert len(changed) == 1 and changed[0].cooked is True and changed[0].rating == 4
    after = path.read_text(encoding="utf-8").splitlines()
    assert len(after) == len(before) == 4
    assert after[0] == before[0] and after[2] == before[2] and after[3] == before[3]  # andere Zeilen byte-gleich
    rec = json.loads(after[1])
    assert rec["cooked"] is True and rec["rating"] == 4 and rec["name"] == "Rezept aufwendig"
    # nur rating, cooked bleibt
    update("2026-11-07_1706:aufwendig", rating=2, path=path)
    r = [x for x in read_all(path) if x.key == "2026-11-07_1706:aufwendig"][0]
    assert r.cooked is True and r.rating == 2
    # nur cooked=False, rating bleibt
    update("2026-11-07_1706:aufwendig", cooked=False, path=path)
    r = [x for x in read_all(path) if x.key == "2026-11-07_1706:aufwendig"][0]
    assert r.cooked is False and r.rating == 2
    assert not list(path.parent.glob("*.tmp"))  # keine temporäre Datei übrig


def test_update_validates_rating_cooked_and_key(path):
    for bad in (0, 6, -1, 3.5, "4", True):
        with pytest.raises(ValueError, match="Bewertung"):
            update("2026-11-07_1706:aufwendig", rating=bad, path=path)
    with pytest.raises(ValueError, match="cooked"):
        update("2026-11-07_1706:aufwendig", cooked="ja", path=path)
    with pytest.raises(ValueError, match="Nichts"):
        update("2026-11-07_1706:aufwendig", path=path)
    with pytest.raises(KeyError):
        update("2026-11-07_1706:budget", cooked=True, path=path)
    assert read_all(path)[1].cooked is None  # nichts verändert
    with pytest.raises(ValidationError):
        RecipeRecord(date=date(2026, 11, 7), variant="budget", name="x", rating=7)


def test_update_changes_all_duplicates_with_same_key(tmp_path):
    p = tmp_path / "recipes.jsonl"
    append(_rec(), p)
    append(_rec(), p)
    changed = update("2026-11-07_1706:aufwendig", cooked=True, path=p)
    assert len(changed) == 2 and all(r.cooked for r in read_all(p))


def test_write_atomic_leaves_valid_file_on_error(path, monkeypatch):
    original = history.os.replace

    def boom(src, dst):
        raise OSError("Platte voll")

    monkeypatch.setattr(history.os, "replace", boom)
    with pytest.raises(OSError):
        update("2026-11-07_1706:aufwendig", cooked=True, path=path)
    monkeypatch.setattr(history.os, "replace", original)
    assert len(read_all(path)) == 4 and read_all(path)[1].cooked is None  # Original unangetastet
    assert not list(path.parent.glob("*.tmp"))
