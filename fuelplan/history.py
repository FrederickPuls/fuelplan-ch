"""Rezept-Archiv: history/recipes.jsonl (gitignored), ein Eintrag pro gewähltem Rezept.

Schritt 6: lesen (letzte 14 Tage für die Plan-User-Message) und anhängen.
Schritt 7 nutzt append beim `shop`.
Phase 2, Schritt 1: Eintrag eindeutig adressierbar über `key` = "<Run-Ordner>:<Variante>" (ohne Run-Ordner:
"<Datum>:<Variante>"), `read_all` für die API und `update(key, cooked=, rating=)` mit Bewertung 1–5.
Das Umschreiben ist atomar (temporäre Datei im selben Ordner + os.replace). Format bleibt JSONL.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from fuelplan import config

RATING_MIN, RATING_MAX = 1, 5
KEY_SEPARATOR = ":"


class RecipeRecord(BaseModel):
    date: date
    variant: str
    name: str
    main_ingredients: list[str] = Field(default_factory=list)
    price_chf_per_portion: float | None = None
    run_dir: str | None = None
    cooked: bool | None = None
    rating: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    dry_run: bool = False  # Einträge aus --dry-run zählen nicht als gekocht/geplant

    @property
    def key(self) -> str:
        """Eindeutige Adresse: Run-Ordner (enthält das Datum) + Variante; ohne Run-Ordner Datum + Variante."""
        return f"{self.run_dir or self.date.isoformat()}{KEY_SEPARATOR}{self.variant}"


def read_all(path: Path = config.HISTORY_FILE) -> list[RecipeRecord]:
    """Alle Einträge in Dateireihenfolge (älteste zuerst), inklusive Dry-Run."""
    path = Path(path)
    if not path.exists():
        return []
    return [RecipeRecord.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_recent(days: int = config.RECENT_RECIPE_DAYS, today: date | None = None,
                path: Path = config.HISTORY_FILE, limit: int = config.MAX_RECENT_RECIPES,
                include_dry_run: bool = False) -> list[RecipeRecord]:
    """Einträge der letzten `days` Tage, neueste zuerst, höchstens `limit`; Dry-Run-Einträge nur auf Wunsch."""
    today = today or config.today()
    cutoff = today - timedelta(days=days)
    records = [rec for rec in read_all(path) if cutoff <= rec.date <= today and (include_dry_run or not rec.dry_run)]
    records.sort(key=lambda r: r.date, reverse=True)
    return records[:limit]


def append(record: RecipeRecord, path: Path = config.HISTORY_FILE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")


def _write_atomic(records: list[RecipeRecord], path: Path) -> None:
    """Alle Einträge neu schreiben: temporäre Datei im selben Ordner, dann umbenennen (nie halb geschrieben)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(rec.model_dump_json() + "\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def update(key: str, cooked: bool | None = None, rating: int | None = None,
           path: Path = config.HISTORY_FILE) -> list[RecipeRecord]:
    """Setzt `cooked` und/oder `rating` für alle Einträge mit diesem Schlüssel (None = unverändert lassen).

    rating muss zwischen 1 und 5 liegen (ValueError), cooked ein bool (ValueError); unbekannter Schlüssel → KeyError.
    Rückgabe: die geänderten Einträge.
    """
    if cooked is None and rating is None:
        raise ValueError("Nichts zu ändern: cooked oder rating angeben.")
    if cooked is not None and not isinstance(cooked, bool):
        raise ValueError("cooked muss ja/nein (bool) sein.")
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or not RATING_MIN <= rating <= RATING_MAX):
        raise ValueError(f"Bewertung muss eine ganze Zahl von {RATING_MIN} bis {RATING_MAX} sein.")
    records = read_all(path)
    changed: list[RecipeRecord] = []
    for i, rec in enumerate(records):
        if rec.key != key:
            continue
        upd: dict = {}
        if cooked is not None:
            upd["cooked"] = cooked
        if rating is not None:
            upd["rating"] = rating
        records[i] = rec.model_copy(update=upd)
        changed.append(records[i])
    if not changed:
        raise KeyError(key)
    _write_atomic(records, path)
    return changed
