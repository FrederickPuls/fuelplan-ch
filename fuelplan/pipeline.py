"""Ablauf eines Laufs in zwei Teilen (Plan Schritt 7, Umbau A1 in Schritt 10).

Teil A (`today`):  Collect → Classify → Plan (LLM 1) → Retrieve (Zutaten ALLER DREI Varianten, gleiche Suchbegriffe
                   nur einmal, Basiszutaten aus dem Preis-Cache) → Execute (LLM 2, EIN Aufruf für alle drei Varianten)
                   → Compute pro Variante (echter Preis/Portion, Einkaufssumme, Budget- und Makro-Checks)
                   → Ausgabe Tagesanalyse + 3 Varianten mit echtem Preis → Auswahl.
Teil B (`shop`):   liest Plan, products.json und execute_response.json aus dem Run-Ordner von Teil A, filtert auf die
                   gewählte Variante, rendert die Einkaufsliste und schreibt ins Archiv. Keine Supermarkt-Abfrage,
                   kein LLM-Aufruf. Run-Ordner von vor Schritt 10 → klare Meldung, `today` neu ausführen.
Genau 2 LLM-Aufrufe pro Lauf, beide in Teil A.
--mock: MockBridge statt swissgroceries. --dry-run: gespeicherte LLM-Antworten (kein Guthaben, kein Netz
für das Modell; Trainingsdaten kommen weiterhin aus CSV bzw. intervals.icu).
Phase 2, Schritt 1 (ohne Verhaltensänderung): zusätzlich zum `log`-Text meldet `on_step(step, detail)` die festen Stufen
STEPS; `load_run` liest einen Run-Ordner als Datenobjekte (Teil B und API nutzen dieselbe Funktion), `load_part_a`
baut daraus wieder ein PartAResult (echte Preise pro Variante, Warnungen, Kosten, gewählte Variante aus shop.json).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from fuelplan import config, history
from fuelplan.checks import check_plan, check_shopping, validate_execute_choices
from fuelplan.compute import ShoppingList, build_shopping_list
from fuelplan.grocery.base import GroceryBridge, Product, QueryBudgetExceeded
from fuelplan.grocery.price_cache import PriceCache, is_base_ingredient
from fuelplan.history import RecipeRecord
from fuelplan.llm.prompts import (EXECUTE_SYSTEM_PROMPT, build_execute_user_message, build_plan_system_prompt,
                                  build_plan_user_message, dinner_share)
from fuelplan.llm.schemas import VARIANTS, ExecuteResponse, PlanResponse, Recipe
from fuelplan.models import DayContext
from fuelplan.nutrition.daytype import classify
from fuelplan.nutrition.needs import compute_needs
from fuelplan.render import render_plan, render_shopping
from fuelplan.runlog import RunDir
from fuelplan.training.garmin_csv import GarminCsvSource
from fuelplan.training.merge import build_day_context

PRE_STEP10_MESSAGE = "Lauf vor Schritt 10 (keine Produktwahl für alle Varianten) – bitte `python -m fuelplan today` neu ausführen."
# Feste Fortschrittsstufen für on_step (Phase 2): Reihenfolge in Teil A
STEPS: tuple[str, ...] = ("collect", "plan", "retrieve", "execute", "compute", "done")
StepCallback = Callable[[str, str], None]


@dataclass
class Retrieved:
    """Ergebnis von Retrieve über alle drei Varianten (wird als products.json gespeichert)."""

    products: dict[str, list[Product]] = field(default_factory=dict)  # Suchbegriff → Treffer (jede Liste nur einmal)
    ingredient_query: dict[str, dict[str, str]] = field(default_factory=dict)  # Variante → Zutat → Suchbegriff
    errors: dict[str, dict[str, str]] = field(default_factory=dict)  # Suchbegriff → {Kette: Grund}
    notes: list[str] = field(default_factory=list)
    queries: int = 0
    source: str = "swissgroceries"

    def for_recipe(self, recipe: Recipe) -> dict[str, list[Product]]:
        keys = self.ingredient_query.get(recipe.variant, {})
        return {i.name: self.products.get(keys.get(i.name, ""), []) for i in recipe.ingredients}

    def to_json(self) -> dict:
        return {"by_query": {k: [p.model_dump(mode="json") for p in v] for k, v in self.products.items()},
                "ingredient_query": self.ingredient_query, "errors": self.errors, "notes": self.notes,
                "queries": self.queries, "source": self.source}

    @classmethod
    def from_json(cls, data: dict) -> "Retrieved":
        return cls(products={k: [Product(**p) for p in v] for k, v in data["by_query"].items()},
                   ingredient_query=data["ingredient_query"], errors=data.get("errors", {}), notes=data.get("notes", []),
                   queries=data.get("queries", 0), source=data.get("source", "swissgroceries"))


@dataclass
class PartAResult:
    run: RunDir
    ctx: DayContext
    plan: PlanResponse
    output: str
    warnings: list[str]
    shopping: dict[str, ShoppingList] = field(default_factory=dict)  # Variante → Einkaufsliste mit echten Preisen
    queries: int = 0
    usage: dict = field(default_factory=dict)  # usage.json: Aufrufe, total_cost_usd, total_tokens
    chosen_variant: str | None = None  # nach Teil B (shop.json), sonst None


@dataclass
class RunData:
    """Rohdaten eines Run-Ordners nach Teil A als Datenobjekte (Grundlage für Teil B und die API)."""

    run: RunDir
    ctx: DayContext
    plan: PlanResponse
    response: ExecuteResponse
    retrieved: Retrieved


@dataclass
class PartBResult:
    run: RunDir
    shopping: ShoppingList
    output: str
    warnings: list[str]


class Pipeline:
    def __init__(self, *, mock: bool = False, dry_run: bool = False, runs_dir: Path | None = None,
                 history_path: Path | None = None, cache_path: Path | None = None,
                 bridge_factory: Callable[[], GroceryBridge] | None = None, llm=None,
                 csv_source=None, api_source_factory: Callable[[], object] | None = None,
                 log: Callable[[str], None] = lambda s: print(s, file=sys.stderr),
                 on_step: StepCallback | None = None) -> None:
        self.mock, self.dry_run = mock, dry_run
        self.runs_dir = runs_dir or config.RUNS_DIR
        self.history_path = history_path or config.HISTORY_FILE
        # Mock-Läufe nie in den echten Preis-Cache schreiben (Mock-Preise würden sonst als „geschätzt“ auftauchen)
        self.cache_path = cache_path or (config.PRICE_CACHE_FILE.with_name("price_cache_mock.json") if mock else config.PRICE_CACHE_FILE)
        self.log = log
        self.on_step: StepCallback = on_step or (lambda step, detail: None)
        self._bridge_factory = bridge_factory
        self._llm = llm
        self._csv_source = csv_source
        self._api_source_factory = api_source_factory

    # --- Bausteine -----------------------------------------------------------------------------
    def llm(self):
        if self._llm is None:
            if self.dry_run:
                from fuelplan.llm.dryrun import DryRunLLM
                self._llm = DryRunLLM()
            else:
                from fuelplan.llm.client import LLMClient
                self._llm = LLMClient()
        return self._llm

    def bridge(self) -> GroceryBridge:
        if self._bridge_factory:
            return self._bridge_factory()
        if self.mock:
            from fuelplan.grocery.mock import MockBridge
            return MockBridge()
        from fuelplan.grocery.swissgroceries import SwissGroceriesBridge
        return SwissGroceriesBridge()

    def day_context(self, day: date) -> DayContext:
        csv_source = self._csv_source or GarminCsvSource()
        api_source = None
        if day > config.CSV_LAST_DAY:
            if self._api_source_factory:
                api_source = self._api_source_factory()
            else:
                from fuelplan.training.intervals import IntervalsSource
                api_source = IntervalsSource()
        ctx = build_day_context(day, csv_source, api_source)
        ctx.classification = classify(ctx)
        ctx.needs = compute_needs(ctx.classification)
        return ctx

    # --- Retrieve (alle drei Varianten) --------------------------------------------------------
    def retrieve(self, plan: PlanResponse, bridge: GroceryBridge, cache: PriceCache) -> Retrieved:
        """Suchbegriffe aller Zutaten aller Rezepte, jeder nur einmal (Gross-/Kleinschreibung egal);
        Basiszutaten aus dem Preis-Cache, sonst Abfrage; Treffer von Basiszutaten in den Cache."""
        out = Retrieved(source="mock" if self.mock else "swissgroceries")
        seen: dict[str, str] = {}  # normalisiert → Schlüssel (erste Schreibweise)
        for recipe in plan.recipes:
            out.ingredient_query[recipe.variant] = {}
            for ing in recipe.ingredients:
                term = " ".join(ing.search_term.split())
                key = seen.get(term.lower())
                if key is None:
                    key = seen[term.lower()] = term
                    base = ing.base_ingredient or is_base_ingredient(term)
                    cached = cache.get(term) if base else None
                    if cached:
                        out.products[key] = cached
                    else:
                        try:
                            r = bridge.search(term)
                        except QueryBudgetExceeded as e:
                            out.notes.append(str(e))
                            out.products[key] = []
                            out.errors[key] = {c: "Abfrage-Limit erreicht" for c in config.GROCERY_CHAINS}
                        else:
                            out.products[key] = r.products
                            if r.errors:
                                out.errors[key] = r.errors
                                for chain, why in r.errors.items():
                                    out.notes.append(f"„{term}“: {chain} nicht verfügbar ({why})")
                            if base and r.products:
                                cache.put(term, r.products)
                out.ingredient_query[recipe.variant][ing.name] = key
        out.queries = bridge.queries_made
        return out

    # --- Teil A --------------------------------------------------------------------------------
    def part_a(self, day: date, run: RunDir | None = None) -> PartAResult:
        """run: vorab angelegter Run-Ordner (API: die run_id steht so schon vor dem Start fest); sonst neu anlegen."""
        self.on_step("collect", f"Trainingsdaten und Tagesanalyse für {day.isoformat()}")
        ctx = self.day_context(day)
        recent = history.read_recent(today=day, path=self.history_path)
        system = build_plan_system_prompt()
        user = build_plan_user_message(ctx, recent)
        run = run or RunDir.create(self.runs_dir)
        run.write_json("day_context.json", ctx.model_dump(mode="json", exclude_none=True))
        run.write_json("plan_request.json", {"model": config.PLAN_MODEL, "effort": config.PLAN_EFFORT, "max_tokens": config.MAX_TOKENS_PLAN,
                                             "system": system, "user": user,
                                             "recent_recipes": [r.model_dump(mode="json") for r in recent]})
        self.on_step("plan", f"Rezepte planen ({'dry-run' if self.dry_run else config.PLAN_MODEL})")
        self.log(f"Plan-Aufruf ({'dry-run' if self.dry_run else config.PLAN_MODEL}) …")
        res = self.llm().complete_json(model=config.PLAN_MODEL, system=system, user=user, schema=PlanResponse,
                                       max_tokens=config.MAX_TOKENS_PLAN, effort=config.PLAN_EFFORT, label="plan")
        run.add_usage(res.usage)
        run.write_json("plan_response.json", res.raw)
        plan: PlanResponse = res.data

        # Retrieve für alle drei Varianten
        n_ings = sum(len(r.ingredients) for r in plan.recipes)
        self.on_step("retrieve", f"Preise suchen ({n_ings} Zutaten, {'Mock' if self.mock else 'swissgroceries'})")
        self.log(f"Produkte für alle drei Varianten ({n_ings} Zutaten, {'Mock' if self.mock else 'swissgroceries'}) …")
        cache = PriceCache(self.cache_path)
        with self.bridge() as bridge:
            retrieved = self.retrieve(plan, bridge, cache)
        run.write_json("products.json", retrieved.to_json())

        # Execute: ein Aufruf für alle drei Varianten
        user_b = build_execute_user_message(plan, retrieved.products, retrieved.ingredient_query, retrieved.errors)
        run.write_json("execute_request.json", {"model": config.EXECUTE_MODEL, "effort": config.EXECUTE_EFFORT, "max_tokens": config.MAX_TOKENS_EXECUTE,
                                                "variants": list(VARIANTS), "system": EXECUTE_SYSTEM_PROMPT, "user": user_b,
                                                "queries": retrieved.queries, "notes": retrieved.notes})
        self.on_step("execute", f"Produkte wählen ({'dry-run' if self.dry_run else config.EXECUTE_MODEL})")
        self.log(f"Execute-Aufruf für alle drei Varianten ({'dry-run' if self.dry_run else config.EXECUTE_MODEL}) …")
        res_b = self.llm().complete_json(model=config.EXECUTE_MODEL, system=EXECUTE_SYSTEM_PROMPT, user=user_b, schema=ExecuteResponse,
                                         max_tokens=config.MAX_TOKENS_EXECUTE, effort=config.EXECUTE_EFFORT, label="execute",
                                         hints={"plan": plan, "products": retrieved.products, "ingredient_query": retrieved.ingredient_query})
        run.add_usage(res_b.usage)
        run.write_json("execute_response.json", res_b.raw)

        # Compute pro Variante
        self.on_step("compute", "Preise und Prüfungen rechnen")
        shopping, warnings = self._compute_all(plan, res_b.data, retrieved)
        target = dinner_share(ctx)
        warnings += check_plan(plan, target, shopping)
        source_note = self._source_note_a(retrieved)
        output = render_plan(ctx, plan, warnings, target, shopping, source_note)
        run.write_text("output_a.md", output)
        run.write_text("output.md", output)
        self.on_step("done", run.name)
        return PartAResult(run=run, ctx=ctx, plan=plan, output=output, warnings=warnings, shopping=shopping,
                           queries=retrieved.queries, usage=run.usage())

    def _source_note_a(self, retrieved: Retrieved) -> str:
        return (f"Produkte: {'Mock-Bridge' if self.mock else 'swissgroceries (Migros, Denner, Coop)'}, {retrieved.queries} Abfragen · "
                f"Modelle: {'dry-run' if self.dry_run else f'{config.PLAN_MODEL} (Plan), {config.EXECUTE_MODEL} (Execute)'}")

    # --- Laden aus dem Run-Ordner (Teil B und API) ---------------------------------------------
    @staticmethod
    def load_run(run: RunDir) -> RunData:
        """Plan, Tagesanalyse, Produktwahl und Treffer aus einem Run-Ordner nach Teil A; Run-Ordner von vor
        Schritt 10 oder unvollständige Läufe → RuntimeError mit klarer Meldung."""
        if not run.has("plan_response.json"):
            raise RuntimeError(f"{run.name}: kein Plan gefunden (Teil A nicht abgeschlossen).")
        if not (run.has("products.json") and run.has("execute_response.json")):
            raise RuntimeError(f"{run.name}: {PRE_STEP10_MESSAGE}")
        products_json = run.read_json("products.json")
        if "by_query" not in products_json or "ingredient_query" not in products_json:
            raise RuntimeError(f"{run.name}: {PRE_STEP10_MESSAGE}")
        try:
            response = ExecuteResponse.model_validate(run.read_json("execute_response.json"))
        except ValidationError as e:
            raise RuntimeError(f"{run.name}: {PRE_STEP10_MESSAGE}") from e
        if response.variants != set(VARIANTS):
            raise RuntimeError(f"{run.name}: {PRE_STEP10_MESSAGE}")
        plan = PlanResponse.model_validate(run.read_json("plan_response.json"))
        ctx = DayContext.model_validate(run.read_json("day_context.json"))
        return RunData(run=run, ctx=ctx, plan=plan, response=response, retrieved=Retrieved.from_json(products_json))

    @staticmethod
    def chosen_variant(run: RunDir) -> str | None:
        """Gewählte Variante nach Teil B aus shop.json (None, wenn noch nicht gewählt; ältere Läufe ohne shop.json: siehe load_part_a)."""
        if run.has("shop.json"):
            variant = run.read_json("shop.json").get("variant")
            return variant if variant in VARIANTS else None
        return None

    def load_part_a(self, run: RunDir) -> PartAResult:
        """PartAResult aus dem Run-Ordner wieder aufbauen: gleiche Rechnung wie in Teil A (echte Preise pro Variante,
        Warnungen), Ausgabe aus output_a.md, Kosten aus usage.json, gewählte Variante aus shop.json."""
        data = self.load_run(run)
        shopping, warnings = self._compute_all(data.plan, data.response, data.retrieved)
        warnings += check_plan(data.plan, dinner_share(data.ctx), shopping)
        output = (run.path / "output_a.md").read_text(encoding="utf-8") if run.has("output_a.md") else ""
        chosen = self.chosen_variant(run)
        if chosen is None:
            chosen = next((r.variant for r in reversed(history.read_all(self.history_path)) if r.run_dir == run.name), None)
        return PartAResult(run=run, ctx=data.ctx, plan=data.plan, output=output, warnings=warnings, shopping=shopping,
                           queries=data.retrieved.queries, usage=run.usage(), chosen_variant=chosen)

    @staticmethod
    def _compute_all(plan: PlanResponse, response: ExecuteResponse, retrieved: Retrieved) -> tuple[dict[str, ShoppingList], list[str]]:
        shopping: dict[str, ShoppingList] = {}
        warnings: list[str] = list(retrieved.notes)
        for recipe in plan.recipes:
            chosen, warns = validate_execute_choices(recipe, response, retrieved.for_recipe(recipe))
            sl = build_shopping_list(recipe, chosen)
            shopping[recipe.variant] = sl
            warnings += [f"{recipe.variant}: {w}" for w in warns + sl.warnings]
        return shopping, warnings

    # --- Teil B --------------------------------------------------------------------------------
    def part_b(self, variant: str, run: RunDir | None = None) -> PartBResult:
        run = run or RunDir.latest_with_plan(self.runs_dir)
        if run is None:
            raise RuntimeError("Kein Lauf mit Plan gefunden. Zuerst `python -m fuelplan today` ausführen.")
        if variant not in VARIANTS:
            raise RuntimeError(f"Unbekannte Variante {variant!r} (budget, schnell, aufwendig).")
        data = self.load_run(run)
        plan, ctx, response, retrieved = data.plan, data.ctx, data.response, data.retrieved
        recipe = plan.by_variant(variant)
        self.log(f"Einkaufsliste für „{recipe.name}“ aus der Produktwahl von Teil A ({run.name}) …")
        chosen, warns = validate_execute_choices(recipe, response, retrieved.for_recipe(recipe))
        sl = build_shopping_list(recipe, chosen)
        target = dinner_share(ctx)
        warnings = retrieved.notes + warns + check_shopping(sl, target)
        model = run.read_json("execute_request.json").get("model", "?") if run.has("execute_request.json") else "?"
        source_note = (f"Produkte aus Teil A ({run.name}): {'Mock-Bridge' if retrieved.source == 'mock' else 'swissgroceries (Migros, Denner, Coop)'}, "
                       f"{retrieved.queries} Abfragen · Modell: {model} · Teil B ohne neue Abfragen und ohne Modellaufruf")
        output = render_shopping(sl, warnings, source_note)
        run.write_text("output_b.md", output)
        output_a = (run.path / "output_a.md").read_text(encoding="utf-8") if run.has("output_a.md") else ""
        run.write_text("output.md", output_a + "\n\n" + output)
        record = RecipeRecord(
            date=ctx.date, variant=variant, name=recipe.name,
            main_ingredients=[i.name for i in recipe.ingredients if not i.base_ingredient][:5],
            price_chf_per_portion=sl.price_per_portion_chf, run_dir=run.name, dry_run=self.dry_run,
        )
        history.append(record, self.history_path)
        # Phase 2: gewählte Variante als Datenobjekt im Run-Ordner (für GET /api/runs/{id} nach Neustart)
        run.write_json("shop.json", {"variant": variant, "recipe_name": recipe.name, "history_key": record.key,
                                     "chosen_at": datetime.now(config.TZ).isoformat(timespec="seconds")})
        return PartBResult(run=run, shopping=sl, output=output, warnings=warnings)
