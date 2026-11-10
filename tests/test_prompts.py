"""Schritt 6/10: Schemas, Prompt-Builder, Archiv, Execute-Prompt und -Validierung für alle drei Varianten – ohne Netz."""

from __future__ import annotations

import warnings
from datetime import date

import pytest
from pydantic import ValidationError

from fuelplan import config
from fuelplan.checks import validate_execute_choices
from fuelplan.grocery.mock import MockBridge
from fuelplan.history import RecipeRecord, append, read_recent
from fuelplan.llm.prompts import (PromptTooLong, build_execute_user_message, build_plan_system_prompt,
                                  build_plan_user_message, dinner_share, load_profile)
from fuelplan.llm.schemas import ExecuteResponse, Ingredient, Macros, PlanResponse, ProductChoice, Recipe
from fuelplan.models import ActivityType, DayContext
from fuelplan.nutrition.daytype import classify
from fuelplan.nutrition.needs import compute_needs
from tests.conftest import make_activity as A


def recipe(variant="schnell", name="Poulet-Reis-Pfanne", ingredients=None) -> Recipe:
    ingredients = ingredients or [
        Ingredient(name="Pouletbrust", grams=150, search_term="Pouletbrust", base_ingredient=False),
        Ingredient(name="Basmati Reis", grams=100, search_term="Basmati Reis", base_ingredient=True),
        Ingredient(name="Broccoli", grams=200, search_term="Broccoli", base_ingredient=False),
    ]
    return Recipe(variant=variant, name=name, description="Schnell.", portions=1, cooking_minutes=20, equipment=["Herd"],
                  ingredients=ingredients, steps=["Reis kochen", "Poulet braten"], estimated_price_chf_per_portion=6.5,
                  estimated_macros_per_portion=Macros(kcal=900, carbs_g=100, protein_g=50, fat_g=25))


def day_ctx(d=date(2026, 11, 3)) -> DayContext:
    ctx = DayContext(date=d, activities=[A(distance_km=6.2, duration_min=40, avg_hr=148, day=d)])
    ctx.classification = classify(ctx)
    ctx.needs = compute_needs(ctx.classification)
    return ctx


# --- Schemas ------------------------------------------------------------------------------------------

def test_plan_requires_exactly_one_recipe_per_variant():
    PlanResponse(recipes=[recipe("budget"), recipe("schnell"), recipe("aufwendig")])
    with pytest.raises(ValidationError, match="Varianten"):
        PlanResponse(recipes=[recipe("budget"), recipe("budget"), recipe("aufwendig")])
    with pytest.raises(ValidationError):
        PlanResponse(recipes=[recipe("budget"), recipe("schnell")])


def test_plan_schema_is_json_schema_with_enum():
    s = PlanResponse.model_json_schema()
    assert s["$defs"]["Recipe"]["properties"]["variant"]["enum"] == ["budget", "schnell", "aufwendig"]


def test_execute_schema_allows_null_choice():
    r = ExecuteResponse(choices=[ProductChoice(variant="budget", ingredient="x", chain=None, product_id=None, packs=None, reason="nichts passt")])
    assert r.choices[0].product_id is None and r.variants == {"budget"} and r.for_variant("schnell") == []
    with pytest.raises(ValidationError):
        ProductChoice(variant="budget", ingredient="x", chain="aldi", product_id="1", packs=1, reason="")
    with pytest.raises(ValidationError):  # variant ist Pflicht (ein Aufruf für alle drei Varianten)
        ProductChoice(ingredient="x", chain=None, product_id=None, packs=None, reason="")
    assert "variant" in ExecuteResponse.model_json_schema()["$defs"]["ProductChoice"]["required"]


# --- Plan-Prompts ---------------------------------------------------------------------------------------

def test_system_prompt_contains_profile_rules_and_budget():
    s = build_plan_system_prompt(load_profile(config.PROFILE_EXAMPLE_FILE))
    assert "70 kg" in s and "Halbmarathon" in s and "Airfryer" in s
    assert "6–7 CHF" in s and "maximal 10 CHF" in s and "30–40 Minuten" in s
    assert "## Profil" in s and "JSON" in s
    assert "## Profil" in load_profile() and "## Profil" in build_plan_system_prompt()  # eigenes oder Beispielprofil


def test_profile_falls_back_to_example_when_profile_md_is_missing(tmp_path):
    example = tmp_path / "profile.example.md"
    example.write_text("# Kopf\n\n## Profil\n- Beispielperson, 70 kg\n", encoding="utf-8")
    assert config.resolve_profile_file(tmp_path) == example  # kein profile.md → Beispielprofil
    assert load_profile(config.resolve_profile_file(tmp_path)) == "## Profil\n- Beispielperson, 70 kg"
    own = tmp_path / "profile.md"
    own.write_text("## Profil\n- Ich, 80 kg\n", encoding="utf-8")
    assert config.resolve_profile_file(tmp_path) == own  # eigenes Profil hat Vorrang
    assert "80 kg" in load_profile(config.resolve_profile_file(tmp_path))


def test_example_profile_is_shipped_and_default_profile_file_exists():
    assert config.PROFILE_EXAMPLE_FILE.exists()
    assert config.PROFILE_FILE.exists() and config.PROFILE_FILE.name in ("profile.md", "profile.example.md")
    text = config.PROFILE_EXAMPLE_FILE.read_text(encoding="utf-8")
    assert "Beispielprofil" in text and "## Profil" in text


def test_dinner_share_uses_meal_split():
    ctx = day_ctx()
    d = dinner_share(ctx)
    assert d["kcal"] == round(ctx.needs.kcal * config_share()) and d["share_pct"] == round(config_share() * 100)


def config_share():
    from fuelplan.nutrition import rules as R
    return R.MEAL_SPLIT["Abendessen"]


def test_plan_user_message_has_analysis_needs_dinner_weekday_and_archive():
    ctx = day_ctx()
    recent = [RecipeRecord(date=date(2026, 11, 2), variant="budget", name="Linsen-Dal", main_ingredients=["Linsen", "Reis"])]
    m = build_plan_user_message(ctx, recent)
    assert "Dienstag, 03.11.2026 (Werktag)" in m
    assert "Lauf" in m and "6.2 km" in m and "Ø-Puls 148" in m
    assert "Easy Run" in m and ctx.classification.reason in m
    assert f"Tagesbedarf gesamt: {ctx.needs.kcal} kcal" in m
    assert f"{dinner_share(ctx)['kcal']} kcal" in m and "Zielwerte für das Abendessen" in m
    assert "02.11. (budget): Linsen-Dal – Linsen, Reis" in m and "nicht wiederholen" in m
    assert "maximal 25" in m


def test_plan_user_message_weekend_and_rest_day_and_empty_archive():
    d = date(2026, 11, 8)  # Sonntag
    ctx = DayContext(date=d)
    ctx.classification = classify(ctx); ctx.needs = compute_needs(ctx.classification)
    m = build_plan_user_message(ctx, [])
    assert "Sonntag" in m and "Wochenende" in m and "kein Training" in m and "noch keine Einträge" in m


def test_recent_recipes_capped_and_long_message_warns(monkeypatch):
    ctx = day_ctx()
    recent = [RecipeRecord(date=date(2026, 11, 2), variant="budget", name=f"Rezept {i}", main_ingredients=["x"]) for i in range(40)]
    m = build_plan_user_message(ctx, recent)
    assert m.count("Rezept ") == config.MAX_RECENT_RECIPES
    monkeypatch.setattr(config, "MAX_USER_MESSAGE_CHARS", 100)
    with pytest.warns(PromptTooLong):
        build_plan_user_message(ctx, recent)


# --- Archiv -----------------------------------------------------------------------------------------------

def test_history_read_recent_filters_window_sorts_and_limits(tmp_path):
    path = tmp_path / "recipes.jsonl"
    for d, name in [(date(2026, 10, 1), "alt"), (date(2026, 11, 2), "gestern"), (date(2026, 10, 25), "vor 9 Tagen")]:
        append(RecipeRecord(date=d, variant="schnell", name=name, main_ingredients=["a"]), path)
    got = read_recent(days=14, today=date(2026, 11, 3), path=path)
    assert [r.name for r in got] == ["gestern", "vor 9 Tagen"]
    assert read_recent(path=tmp_path / "missing.jsonl") == []
    assert [r.name for r in read_recent(days=14, today=date(2026, 11, 3), path=path, limit=1)] == ["gestern"]


def test_archive_entry_from_yesterday_appears_in_plan_message(tmp_path):
    path = tmp_path / "recipes.jsonl"
    append(RecipeRecord(date=date(2026, 11, 2), variant="aufwendig", name="Lachs mit Süsskartoffel", main_ingredients=["Lachs", "Süsskartoffel"]), path)
    m = build_plan_user_message(day_ctx(), read_recent(today=date(2026, 11, 3), path=path))
    assert "Lachs mit Süsskartoffel – Lachs, Süsskartoffel" in m


# --- Execute-Prompt und Validierung (Schritt 10: alle drei Varianten in einem Aufruf) ------------------

def plan3(schnell: Recipe | None = None) -> PlanResponse:
    budget = recipe("budget", "Linsen-Dal", [
        Ingredient(name="Rote Linsen", grams=120, search_term="Rote Linsen", base_ingredient=True),
        Ingredient(name="Basmati Reis", grams=100, search_term="basmati reis", base_ingredient=True),  # gleicher Begriff, andere Schreibweise
        Ingredient(name="Zwiebel", grams=80, search_term="Zwiebeln", base_ingredient=False)])
    aufwendig = recipe("aufwendig", "Lachs", [
        Ingredient(name="Lachsfilet", grams=180, search_term="Lachs", base_ingredient=False),
        Ingredient(name="Broccoli", grams=250, search_term="Broccoli", base_ingredient=False)])
    return PlanResponse(recipes=[budget, schnell or recipe(), aufwendig])


def _retrieve(plan: PlanResponse, bridge=None):
    """Wie Pipeline.retrieve, ohne Cache: Suchbegriff → Treffer (jeder nur einmal), Variante → Zutat → Suchbegriff."""
    bridge = bridge or MockBridge()
    products, errs, iq = {}, {}, {}
    for r in plan.recipes:
        iq[r.variant] = {}
        for ing in r.ingredients:
            key = next((k for k in products if k.lower() == ing.search_term.lower()), None)
            if key is None:
                key = ing.search_term
                res = bridge.search(key)
                products[key] = res.products
                if res.errors:
                    errs[key] = res.errors
            iq[r.variant][ing.name] = key
    return products, iq, errs


def _products_for(rec: Recipe, bridge=None) -> dict[str, list]:
    """Zutatname → Treffer einer Variante (für validate_execute_choices)."""
    bridge = bridge or MockBridge()
    return {ing.name: bridge.search(ing.search_term).products for ing in rec.ingredients}


def test_execute_message_lists_each_search_term_once_then_variants():
    plan = plan3()
    products, iq, errs = _retrieve(plan)
    m = build_execute_user_message(plan, products, iq, errs)
    assert m.count("### Liste ") == len(products) == 6  # 8 Zutaten; „Basmati Reis“ und „Broccoli“ je nur einmal
    assert "### Liste 1: „Rote Linsen“" in m and "id=mock-migros-000" in m and "AKTION statt 8.10" in m
    assert m.count("id=mock-migros-000") == 1  # Pouletbrust-Liste steht nur einmal
    assert "- denner: keine Treffer" in m  # Broccoli gibt es im Mock nicht bei Denner
    assert "## Varianten und Zutaten" in m
    for v, name in (("budget", "Linsen-Dal"), ("schnell", "Poulet-Reis-Pfanne"), ("aufwendig", "Lachs")):
        assert f"### Variante {v}: {name} (1 Portion(en))" in m
    reis = iq["budget"]["Basmati Reis"]
    n = list(products).index(reis) + 1
    assert f"- Basmati Reis – benötigt 100 g – Liste {n} (Basiszutat)" in m and f"- Basmati Reis – benötigt 100 g – Liste {n} (Basiszutat)" in m
    assert "- Pouletbrust – benötigt 150 g – Liste " in m
    assert "`variant` und Zutatnamen exakt übernehmen" in m
    assert len(m) < config.MAX_EXECUTE_USER_MESSAGE_CHARS


def test_execute_message_marks_chain_errors_no_products_and_missing_list():
    sch = recipe(ingredients=[Ingredient(name="Drachenfrucht", grams=100, search_term="Drachenfrucht", base_ingredient=False),
                              Ingredient(name="Eier", grams=120, search_term="Eier", base_ingredient=False)])
    plan = plan3(sch)
    products, iq, errs = _retrieve(plan, MockBridge(failing_chains=("coop",)))
    m = build_execute_user_message(plan, products, iq, errs)
    assert "- coop: nicht verfügbar (Mock: Kette nicht erreichbar)" in m and "kein Produkt wählbar" in m
    del iq["schnell"]["Eier"]
    m2 = build_execute_user_message(plan, products, iq, errs)
    assert "- Eier – benötigt 120 g – keine Liste, null setzen" in m2


def test_execute_message_caps_products_per_chain_and_warns_when_long(monkeypatch):
    monkeypatch.setattr(config, "MAX_PRODUCTS_PER_CHAIN_AND_INGREDIENT", 1)
    plan = plan3()
    products, iq, _ = _retrieve(plan)
    products["Pouletbrust"] = products["Pouletbrust"] * 3
    m = build_execute_user_message(plan, products, iq)
    assert m.count("id=mock-migros-000") == 1
    monkeypatch.setattr(config, "MAX_EXECUTE_USER_MESSAGE_CHARS", 100)
    with pytest.warns(PromptTooLong, match="Execute-User-Message"):
        build_execute_user_message(plan, products, iq)


def test_validate_execute_choices_accepts_known_ids_and_rejects_unknown():
    rec = recipe()
    products = _products_for(rec)
    resp = ExecuteResponse(choices=[
        ProductChoice(variant="schnell", ingredient="Pouletbrust", chain="coop", product_id="mock-coop-002", packs=1, reason="Aktion"),
        ProductChoice(variant="schnell", ingredient="Basmati Reis", chain="denner", product_id="erfunden-123", packs=1, reason="günstig"),
        ProductChoice(variant="schnell", ingredient="Broccoli", chain=None, product_id=None, packs=None, reason="nichts passt"),
    ])
    chosen, warns = validate_execute_choices(rec, resp, products)
    assert chosen["Pouletbrust"][1].product_id == "mock-coop-002" and chosen["Pouletbrust"][0].packs == 1
    assert chosen["Basmati Reis"][1] is None and "verworfen" in chosen["Basmati Reis"][0].reason
    assert chosen["Broccoli"][1] is None
    assert len(warns) == 1 and "erfunden-123" in warns[0]


def test_validate_execute_choices_only_uses_own_variant():
    rec = recipe()  # schnell
    products = _products_for(rec)
    resp = ExecuteResponse(choices=[
        ProductChoice(variant="budget", ingredient="Pouletbrust", chain="coop", product_id="mock-coop-002", packs=3, reason="andere Variante"),
        ProductChoice(variant="schnell", ingredient="Pouletbrust", chain="migros", product_id="mock-migros-000", packs=1, reason="eigene"),
        ProductChoice(variant="schnell", ingredient="Basmati Reis", chain=None, product_id=None, packs=None, reason=""),
        ProductChoice(variant="schnell", ingredient="Broccoli", chain=None, product_id=None, packs=None, reason=""),
        ProductChoice(variant="aufwendig", ingredient="Lachsfilet", chain=None, product_id=None, packs=None, reason=""),
    ])
    chosen, warns = validate_execute_choices(rec, resp, products)
    assert chosen["Pouletbrust"][1].product_id == "mock-migros-000" and chosen["Pouletbrust"][0].reason == "eigene"
    assert warns == []  # Wahlen anderer Varianten sind keine „unbekannten Zutaten“


def test_validate_execute_choices_missing_ingredient_and_extra():
    rec = recipe()
    products = _products_for(rec)
    resp = ExecuteResponse(choices=[ProductChoice(variant="schnell", ingredient="Fremd", chain=None, product_id=None, packs=None, reason="")])
    chosen, warns = validate_execute_choices(rec, resp, products)
    assert all(v[1] is None for v in chosen.values()) and len(chosen) == 3
    assert all(v[0].variant == "schnell" for v in chosen.values())
    assert any("keine Wahl" in w for w in warns) and any("unbekannte Zutaten" in w for w in warns)
