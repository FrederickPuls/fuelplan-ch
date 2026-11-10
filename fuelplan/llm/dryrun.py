"""Dry-Run-LLM: gespeicherte Antworten aus tests/fixtures/llm/ statt echter Aufrufe (kein Guthaben, kein Netz).

Plan: immer plan_response.json. Execute (Schritt 10, ein Aufruf für alle drei Varianten): pro Variante die
Wahlen aus execute_response.json, wenn deren Zutatnamen zum Rezept der Variante passen; sonst ein deterministischer
Ersatz (günstigstes Produkt nach Grundpreis aus der Liste der Zutat, Packungen nach Bedarf).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from fuelplan import config
from fuelplan.grocery.base import Product
from fuelplan.llm.client import LLMResult, Usage
from fuelplan.llm.schemas import ExecuteResponse, PlanResponse, ProductChoice

FIXTURES_DIR = config.ROOT / "tests" / "fixtures" / "llm"


def cheapest_choice(variant: str, ingredient_name: str, grams: int, products: list[Product]) -> ProductChoice:
    usable = [p for p in products if p.price_chf > 0]
    if not usable:
        return ProductChoice(variant=variant, ingredient=ingredient_name, chain=None, product_id=None, packs=None, reason="Dry-Run: keine Treffer")

    def unit(p: Product) -> float:
        if p.size_g:
            return p.price_chf / p.size_g
        return p.price_chf  # Stückware: Packungspreis

    best = min(usable, key=unit)
    packs = max(1, math.ceil(grams / best.size_g)) if best.size_g else 1
    return ProductChoice(variant=variant, ingredient=ingredient_name, chain=best.chain, product_id=best.product_id, packs=packs,
                         reason="Dry-Run: günstigster Grundpreis")


class DryRunLLM:
    def __init__(self, fixtures_dir: Path = FIXTURES_DIR) -> None:
        self.dir = Path(fixtures_dir)

    def _usage(self, model: str, label: str) -> Usage:
        return Usage(model=f"{model} (dry-run)", label=label, cost_source="dry-run", provider="fixture")

    def _fixture_choices(self) -> dict[str, list[ProductChoice]]:
        path = self.dir / "execute_response.json"
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, list[ProductChoice]] = {}
        for c in raw.get("choices", []):
            choice = ProductChoice.model_validate(c)
            out.setdefault(choice.variant, []).append(choice)
        return out

    def complete_json(self, *, model: str, system: str, user: str, schema, max_tokens: int, label: str = "json",
                      effort: str | None = None, hints: dict | None = None) -> LLMResult:
        if schema is PlanResponse:
            raw = json.loads((self.dir / "plan_response.json").read_text(encoding="utf-8"))
            return LLMResult(data=PlanResponse.model_validate(raw), usage=self._usage(model, label), raw=raw)
        if schema is ExecuteResponse:
            plan: PlanResponse | None = (hints or {}).get("plan")
            if plan is None:
                raise ValueError("Dry-Run Execute braucht hints={'plan': ..., 'products': ..., 'ingredient_query': ...}")
            products: dict[str, list[Product]] = (hints or {}).get("products", {})
            ingredient_query: dict[str, dict[str, str]] = (hints or {}).get("ingredient_query", {})
            fixture = self._fixture_choices()
            choices: list[ProductChoice] = []
            for recipe in plan.recipes:
                fx = fixture.get(recipe.variant, [])
                if fx and {c.ingredient for c in fx} == {i.name for i in recipe.ingredients}:
                    choices += fx
                    continue
                keys = ingredient_query.get(recipe.variant, {})
                choices += [cheapest_choice(recipe.variant, i.name, i.grams, products.get(keys.get(i.name, i.name), []))
                            for i in recipe.ingredients]
            data = ExecuteResponse(choices=choices)
            return LLMResult(data=data, usage=self._usage(model, label), raw=data.model_dump(mode="json"))
        raise ValueError(f"Dry-Run kennt kein Schema {schema.__name__}")
