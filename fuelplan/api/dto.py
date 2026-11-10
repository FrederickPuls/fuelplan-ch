"""Antwortmodelle der API (Phase 2, Schritt 2): dünne Hüllen um die bestehenden pydantic-Modelle.

Keine Rechnung hier – Zahlen kommen aus PartAResult, ShoppingList, RecipeRecord, month_summary. Fehler gehen als
{"error": {"code", "message", ...}} mit verständlichem deutschem Text raus: keine Stacktraces, keine Keys, keine Pfade.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from fuelplan import config
from fuelplan.checklist import ChecklistItem  # noqa: F401 – Teil der API-Antwort
from fuelplan.compute import ShoppingList
from fuelplan.history import RATING_MAX, RATING_MIN, RecipeRecord
from fuelplan.llm.schemas import VARIANTS, Recipe, Variant
from fuelplan.models import DayContext

RunStatusValue = Literal["running", "done", "error", "incomplete"]


# --- Fehler ---------------------------------------------------------------------------------------

class ErrorInfo(BaseModel):
    code: str  # z. B. credits_exhausted, rate_limited, training_unavailable, grocery_unavailable, run_outdated
    message: str  # verständlicher deutscher Text für die App
    detail: str | None = None  # Originalmeldung aus Phase 1, bereinigt (keine Pfade, keine Keys)
    run_id: str | None = None  # bei 409: der laufende Lauf


class ErrorResponse(BaseModel):
    error: ErrorInfo


_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")
_HOME_RE = re.compile(re.escape(str(config.ROOT.parent)) + r"[^\s'\"]*")


def sanitize(text: str) -> str:
    """Pfade ausserhalb des Repos und alles, was wie ein Key aussieht, aus Meldungen entfernen."""
    text = text.replace(str(config.ROOT), "<repo>")  # zuerst das Repo, dann alles andere unterhalb des Elternordners
    text = _HOME_RE.sub("<pfad>", text)
    return _KEY_RE.sub("***", text)


class APIError(Exception):
    """Fehler mit HTTP-Status und ErrorInfo; wird vom Handler in app.py als JSON ausgegeben."""

    def __init__(self, status: int, code: str, message: str, detail: str | None = None, run_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.info = ErrorInfo(code=code, message=message, detail=sanitize(detail) if detail else None, run_id=run_id)


def translate_exception(e: BaseException) -> APIError:
    """Fehler aus Phase 1 → Status + Code + deutscher Text. Unbekannte Fehler → 500 ohne Details."""
    from fuelplan.grocery.swissgroceries import SwissGroceriesError
    from fuelplan.llm.client import CreditsExhausted, LLMError, ProviderUnavailable, RateLimited
    from fuelplan.pipeline import PRE_STEP10_MESSAGE
    from fuelplan.training import TrainingDataError

    if isinstance(e, APIError):
        return e
    text = str(e)
    if isinstance(e, CreditsExhausted):
        return APIError(402, "credits_exhausted", "OpenRouter-Guthaben leer oder Key-Limit erreicht. Guthaben aufladen oder Limit erhöhen, dann neu starten.", text)
    if isinstance(e, RateLimited):
        return APIError(429, "rate_limited", "Das Modell ist gerade ausgelastet (Rate-Limit). In ein paar Minuten nochmals versuchen.", text)
    if isinstance(e, ProviderUnavailable):
        return APIError(503, "provider_unavailable", "Der Modell-Anbieter ist gerade nicht erreichbar. Später nochmals versuchen.", text)
    if isinstance(e, LLMError):
        return APIError(502, "llm_error", "Die Antwort des Modells war unbrauchbar. Lauf neu starten; bleibt es dabei, Limits in config.py prüfen.", text)
    if isinstance(e, TrainingDataError):
        return APIError(503, "training_unavailable", "Trainingsdaten nicht verfügbar: intervals.icu ist nicht erreichbar oder lehnt den Zugriff ab. Ohne Trainingsdaten gibt es keine Tagesanalyse.", text)
    if isinstance(e, SwissGroceriesError):
        return APIError(503, "grocery_unavailable", "Supermarkt-Preise nicht abrufbar: swissgroceries bzw. Coop antwortet nicht (Bot-Schutz oder Dienst gestört). Später nochmals versuchen.", text)
    if isinstance(e, RuntimeError) and PRE_STEP10_MESSAGE in text:
        return APIError(409, "run_outdated", "Dieser Lauf stammt von vor Schritt 10 und hat keine Produktwahl für alle Varianten. Bitte einen neuen Lauf starten.", text)
    if isinstance(e, RuntimeError) and "fehlt in .env" in text:
        return APIError(500, "config_error", "Konfiguration unvollständig: ein Schlüssel fehlt in .env (siehe .env.example).", text)
    if isinstance(e, RuntimeError) and ("Kein Lauf" in text or "kein Plan" in text):
        return APIError(404, "run_not_found", "Kein abgeschlossener Lauf gefunden. Zuerst Vorschläge erstellen.", text)
    return APIError(500, "internal_error", "Unerwarteter Fehler im Server. Details stehen im Terminal, in dem `serve` läuft.")


# --- Tagesanalyse ---------------------------------------------------------------------------------

class DayDTO(BaseModel):
    date: date
    context: DayContext  # Trainings, Wochenschnitt, Klassifikation, Bedarf (bestehendes Modell)
    day_type_label: str | None = None  # z. B. "Kraft + Locker (Surf)"
    dinner_target: dict[str, int] = Field(default_factory=dict)  # kcal, carbs_g, protein_g, fat_g, share_pct
    meal_split: dict[str, float] = Field(default_factory=dict)  # Anteil pro Mahlzeit aus rules.MEAL_SPLIT
    source: str = ""  # "Garmin-CSV" | "intervals.icu"

    @classmethod
    def from_context(cls, ctx: DayContext) -> "DayDTO":
        from fuelplan.llm.prompts import dinner_share
        from fuelplan.nutrition import rules

        return cls(date=ctx.date, context=ctx, day_type_label=ctx.classification.label if ctx.classification else None,
                   dinner_target=dinner_share(ctx) if ctx.needs else {}, meal_split=dict(rules.MEAL_SPLIT),
                   source="Garmin-CSV" if ctx.date <= config.CSV_LAST_DAY else "intervals.icu")


# --- Einkaufsliste mit Summen pro Laden (Block 3) ---------------------------------------------------

class ShoppingListDTO(ShoppingList):
    """ShoppingList plus Summen pro Laden, damit das Frontend nicht rechnet (Abweichung 3.1)."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def store_totals(self) -> dict[str, float]:
        """Einkaufssumme (ganze Packungen) pro Laden, Reihenfolge wie in der Liste; Zeilen ohne Produkt zählen nicht."""
        totals: dict[str, float] = {}
        for line in self.lines:
            if line.product is None:
                continue
            totals[line.product.chain] = round(totals.get(line.product.chain, 0.0) + line.total_chf, 2)
        return totals

    @computed_field  # type: ignore[prop-decorator]
    @property
    def store_has_estimates(self) -> dict[str, bool]:
        """Pro Laden: enthält die Summe geschätzte Preise?"""
        out: dict[str, bool] = {}
        for line in self.lines:
            if line.product is None:
                continue
            out[line.product.chain] = out.get(line.product.chain, False) or line.estimated
        return out

    @classmethod
    def wrap(cls, sl: ShoppingList) -> "ShoppingListDTO":
        return cls.model_validate(sl.model_dump())


# --- Läufe ----------------------------------------------------------------------------------------

class UsageSummary(BaseModel):
    calls: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    dry_run: bool = False

    @classmethod
    def from_usage(cls, usage: dict) -> "UsageSummary":
        calls = usage.get("calls", [])
        return cls(calls=len(calls), total_cost_usd=usage.get("total_cost_usd", 0.0), total_tokens=usage.get("total_tokens", 0),
                   dry_run=any(c.get("cost_source") == "dry-run" for c in calls))


class RunStarted(BaseModel):
    run_id: str
    status: RunStatusValue = "running"


class RunResult(BaseModel):
    """Status und Ergebnis eines Laufs. Bei status != done sind day/recipes/shopping leer."""

    run_id: str
    status: RunStatusValue
    step: str | None = None  # letzte gemeldete Stufe (collect … done)
    error: ErrorInfo | None = None
    day: DayDTO | None = None
    recipes: list[Recipe] = Field(default_factory=list)  # Reihenfolge budget, schnell, aufwendig
    shopping: dict[str, ShoppingListDTO] = Field(default_factory=dict)  # Variante → Einkaufsliste mit echten Preisen und Summen pro Laden
    warnings: list[str] = Field(default_factory=list)
    queries: int = 0
    usage: UsageSummary | None = None
    chosen_variant: Variant | None = None
    mock: bool = False
    dry_run: bool = False

    @classmethod
    def from_part_a(cls, a, *, mock: bool, dry_run: bool) -> "RunResult":  # a: pipeline.PartAResult
        return cls(run_id=a.run.name, status="done", step="done", day=DayDTO.from_context(a.ctx),
                   recipes=[a.plan.by_variant(v) for v in VARIANTS], shopping={v: ShoppingListDTO.wrap(sl) for v, sl in a.shopping.items()}, warnings=a.warnings,
                   queries=a.queries, usage=UsageSummary.from_usage(a.usage), chosen_variant=a.chosen_variant,
                   mock=mock, dry_run=dry_run)


# --- Teil B / Checkliste --------------------------------------------------------------------------

class ShopRequest(BaseModel):
    variant: Variant


class ShopResponse(BaseModel):
    run_id: str
    variant: Variant
    shopping: ShoppingListDTO
    warnings: list[str] = Field(default_factory=list)
    history_key: str


class Checklist(BaseModel):
    run_id: str
    variant: Variant
    items: list[ChecklistItem]
    checked_count: int = 0
    total: int = 0


class ChecklistPatch(BaseModel):
    items: list[ChecklistItem] = Field(min_length=1)


# --- Archiv ---------------------------------------------------------------------------------------

class HistoryEntry(BaseModel):
    key: str
    record: RecipeRecord

    @classmethod
    def from_record(cls, r: RecipeRecord) -> "HistoryEntry":
        return cls(key=r.key, record=r)


class HistoryPatch(BaseModel):
    cooked: bool | None = None
    rating: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)


# --- Kosten ---------------------------------------------------------------------------------------

class UsageResponse(BaseModel):
    month: str  # YYYY-MM
    summary: dict  # runlog.month_summary
    credits: dict | None = None  # openrouter.credits() oder None
    credits_note: str | None = None
