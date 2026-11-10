"""Kompletter Lauf mit Mock-Bridge + gespeicherten LLM-Antworten: Format, Summen, Archiv, Run-Ordner. Ohne Netz.
Schritt 10: Teil A hat echte Preise für alle drei Varianten (Retrieve + ein Execute für alle), Teil B macht keine
Abfrage und keinen LLM-Aufruf."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from fuelplan import config
from fuelplan.checks import check_plan, check_shopping
from fuelplan.compute import PIECE_WEIGHTS_G, ShoppingList, build_shopping_list, compute_macros, proportional_cost
from fuelplan.grocery.base import Nutrition100g, Product
from fuelplan.grocery.mock import MockBridge
from fuelplan.history import read_recent
from fuelplan.llm.dryrun import DryRunLLM, cheapest_choice
from fuelplan.llm.schemas import ExecuteResponse, Ingredient, Macros, PlanResponse, ProductChoice, Recipe
from fuelplan.pipeline import Pipeline
from fuelplan.runlog import RunDir
from fuelplan.training.garmin_csv import GarminCsvSource

FX = config.ROOT / "tests" / "fixtures" / "llm"
CSV_FIXTURE = config.ROOT / "tests" / "fixtures" / "garmin_activities_sample.csv"


@pytest.fixture
def csv_source(tmp_path):
    """Kleine CSV mit erfundenen Einheiten im Format des Garmin-Exports, damit der Test ohne data/ läuft."""
    p = tmp_path / "acts.csv"
    p.write_text(
        "date,time,type,name,duration_min,distance_km,avg_hr,max_hr,kcal,training_load,aerobic_te,anaerobic_te,te_label,z1_min,z2_min,z3_min,z4_min,z5_min\n"
        "2026-11-01,09:00,running,Zürich Laufen,75.0,12.4,158.0,176.0,880.0,110.0,3.5,0.0,AEROBIC_BASE,1,2,3,4,5\n"
        "2026-11-02,18:00,strength_training,Krafttraining,55.0,0.0,115.0,,310.0,14.0,,,AEROBIC_BASE,,,,,\n"
        "2026-11-03,18:30,running,Zürich Laufen,40.0,6.2,148.0,168.0,455.0,62.0,3.0,0.0,AEROBIC_BASE,1,2,3,4,5\n"
    )
    return GarminCsvSource(p, tmp_path / "no_daily.csv")


@pytest.fixture
def pipe(tmp_path, csv_source):
    return Pipeline(mock=True, dry_run=True, runs_dir=tmp_path / "runs", history_path=tmp_path / "history" / "recipes.jsonl",
                    cache_path=tmp_path / "cache" / "prices.json", csv_source=csv_source, log=lambda s: None)


class _NoBridge:
    """Bridge-Factory für Teil B: jede Abfrage wäre ein Fehler."""

    def __call__(self):
        raise AssertionError("Teil B darf keine Supermarkt-Abfrage machen")


class _NoLLM:
    def complete_json(self, **kw):
        raise AssertionError("Teil B darf keinen LLM-Aufruf machen")


def test_full_run_mock_dry_run(pipe, tmp_path):
    a = pipe.part_a(date(2026, 11, 3))
    # Teil A: Tagesanalyse + 3 Varianten mit echtem Preis pro Portion
    assert "## Tagesanalyse – Di 03.11.2026" in a.output and "**Tag-Typ: Easy Run**" in a.output
    for v in ("### Budget:", "### Schnell:", "### Aufwendig:"):
        assert v in a.output
    assert len(re.findall(r"\*\*Preis pro Portion: [\d.]+ CHF \(echt.*· Schätzung [\d.]+ CHF\*\*", a.output)) == 3
    assert "Preis pro Portion (geschätzt)" not in a.output and "Einkauf gesamt" in a.output
    assert "Makros pro Portion (geschätzt)" in a.output and "ohne neue Abfragen und ohne Modellaufruf" in a.output
    assert set(a.shopping) == {"budget", "schnell", "aufwendig"} and all(isinstance(x, ShoppingList) for x in a.shopping.values())
    # Run-Ordner nach Teil A: Produkte, Execute, usage mit genau zwei Aufrufen
    for name in ("day_context.json", "plan_request.json", "plan_response.json", "products.json", "execute_request.json",
                 "execute_response.json", "usage.json", "output_a.md", "output.md"):
        assert a.run.has(name), name
    u = a.run.read_json("usage.json")
    assert [c["label"] for c in u["calls"]] == ["plan", "execute"] and u["calls"][0]["cost_source"] == "dry-run"
    assert not (tmp_path / "runs" / "llm_usage.jsonl").exists()  # Dry-Run nicht im Kostenlog
    pj = a.run.read_json("products.json")
    assert set(pj["ingredient_query"]) == {"budget", "schnell", "aufwendig"} and pj["queries"] == a.queries > 0
    assert set(pj["by_query"]) >= set(pj["ingredient_query"]["schnell"].values())
    resp = json.loads((a.run.path / "execute_response.json").read_text())
    assert {c["variant"] for c in resp["choices"]} == {"budget", "schnell", "aufwendig"}
    assert len(resp["choices"]) == sum(len(r.ingredients) for r in a.plan.recipes)

    # Teil B: keine Abfrage, kein LLM-Aufruf
    pipe._bridge_factory, pipe._llm = _NoBridge(), _NoLLM()
    b = pipe.part_b("schnell", a.run)
    sl = b.shopping
    assert sl.price_per_portion_chf == a.shopping["schnell"].price_per_portion_chf  # gleiche Produktwahl wie Teil A
    assert "| Zutat | Laden | Produkt | Packungsgrösse | Anzahl | Preis CHF | Gesamt CHF | Aktion? |" in b.output
    rows = [l for l in b.output.splitlines() if l.startswith("| ") and not l.startswith("| Zutat") ]
    assert len(rows) == len(sl.lines) == 7
    assert sl.total_chf == pytest.approx(sum(l.total_chf for l in sl.lines), abs=0.01)
    assert sl.proportional_total_chf == pytest.approx(sum(l.proportional_chf for l in sl.lines), abs=0.02)
    assert sl.price_per_portion_chf == pytest.approx(sl.proportional_total_chf / sl.portions, abs=0.01)
    assert f"**Gesamtsumme Einkauf (ganze Packungen): {sl.total_chf:.2f} CHF**" in b.output
    assert "Rapsöl" in b.output and "(geschätzt)" in b.output and sl.has_estimates
    assert "Abweichung" in b.output and "Produktwahl (Begründung des Modells)" in b.output
    assert "ohne neue Abfragen und ohne Modellaufruf" in b.output
    assert 5.0 < sl.price_per_portion_chf < 9.0  # Eier anteilig, nicht ganze Packung
    assert b.run.has("output_b.md")
    assert "Teil A" in (b.run.path / "output.md").read_text() and "Teil B" in (b.run.path / "output.md").read_text()
    assert len(b.run.read_json("usage.json")["calls"]) == 2  # Teil B hat nichts hinzugefügt
    recent = read_recent(today=date(2026, 11, 3), path=pipe.history_path, include_dry_run=True)
    assert len(recent) == 1 and recent[0].name.startswith("Poulet") and recent[0].variant == "schnell" and recent[0].dry_run
    assert read_recent(today=date(2026, 11, 3), path=pipe.history_path) == []  # Dry-Run nicht im echten Archiv


def test_part_b_rejects_run_from_before_step_10(pipe, tmp_path):
    a = pipe.part_a(date(2026, 11, 3))
    (a.run.path / "execute_response.json").unlink()
    with pytest.raises(RuntimeError, match="vor Schritt 10"):
        pipe.part_b("schnell", a.run)
    # altes Format: products.json nach Zutat, Execute ohne variant
    a.run.write_json("products.json", {"Pouletbrust": []})
    a.run.write_json("execute_response.json", {"choices": [{"ingredient": "Pouletbrust", "chain": None, "product_id": None, "packs": None, "reason": ""}]})
    with pytest.raises(RuntimeError, match="vor Schritt 10"):
        pipe.part_b("schnell", a.run)


def test_retrieve_queries_each_search_term_once(pipe):
    a = pipe.part_a(date(2026, 11, 3))
    terms = [i.search_term for r in a.plan.recipes for i in r.ingredients]
    unique = {" ".join(t.split()).lower() for t in terms}
    pj = a.run.read_json("products.json")
    assert len(terms) > len(unique) == len(pj["by_query"])  # Olivenöl/Knoblauch kommen mehrfach vor
    assert a.queries <= len(unique) and a.queries > 0
    assert a.run.read_json("execute_request.json")["user"].count("### Liste ") == len(unique)


def test_retrieve_dedupes_case_and_whitespace(pipe):
    from fuelplan.grocery.price_cache import PriceCache
    from fuelplan.llm.schemas import Ingredient, Macros, Recipe
    def r(variant, term):
        return Recipe(variant=variant, name=variant, description="d", portions=1, cooking_minutes=20, equipment=["Herd"],
                      ingredients=[Ingredient(name="Poulet", grams=200, search_term=term, base_ingredient=False),
                                   Ingredient(name="Reis", grams=100, search_term="Basmati Reis", base_ingredient=True)],
                      steps=["a", "b"], estimated_price_chf_per_portion=6.0,
                      estimated_macros_per_portion=Macros(kcal=900, carbs_g=100, protein_g=50, fat_g=25))
    plan = PlanResponse(recipes=[r("budget", "Pouletbrust"), r("schnell", "pouletbrust "), r("aufwendig", " POULETBRUST")])
    with MockBridge() as bridge:
        got = pipe.retrieve(plan, bridge, PriceCache(pipe.cache_path))
    assert list(got.products) == ["Pouletbrust", "Basmati Reis"] and got.queries == 2
    assert all(got.ingredient_query[v]["Poulet"] == "Pouletbrust" for v in ("budget", "schnell", "aufwendig"))
    assert got.for_recipe(plan.by_variant("schnell"))["Poulet"] == got.products["Pouletbrust"]


def test_shop_uses_latest_run_and_other_variant_via_fallback(pipe):
    pipe.part_a(date(2026, 11, 3))
    b = pipe.part_b("budget")  # kein run übergeben → letzter Lauf; Execute-Fixture passt nicht → Dry-Run-Ersatz
    assert b.shopping.variant == "budget" and b.shopping.recipe_name.startswith("Pasta")
    assert any(l.product is not None for l in b.shopping.lines)
    assert all("Dry-Run" in l.reason for l in b.shopping.lines if l.product is not None)


def test_mock_pipeline_uses_separate_cache_file():
    assert Pipeline(mock=True, dry_run=True).cache_path.name == "price_cache_mock.json"
    assert Pipeline(mock=False, dry_run=True).cache_path == config.PRICE_CACHE_FILE


def test_shop_without_plan_raises(tmp_path, csv_source):
    p = Pipeline(mock=True, dry_run=True, runs_dir=tmp_path / "empty", history_path=tmp_path / "h.jsonl", csv_source=csv_source, log=lambda s: None)
    with pytest.raises(RuntimeError, match="Zuerst"):
        p.part_b("schnell")


def test_base_ingredients_come_from_cache_on_second_run(pipe):
    a1 = pipe.part_a(date(2026, 11, 3))
    a2 = pipe.part_a(date(2026, 11, 3))
    assert a2.queries < a1.queries  # Sojasauce, Olivenöl … (Basiszutaten) kommen beim zweiten Mal aus dem Cache
    assert any(l.estimated and l.product is not None for l in a2.shopping["schnell"].lines)
    assert "Preis aus Cache (geschätzt)" in a2.output
    b2 = pipe.part_b("schnell", a2.run)
    assert "Preis aus Cache (geschätzt)" in b2.output


# --- compute ---------------------------------------------------------------------------------------------

def prod(chain="migros", pid="1", name="x", size=500, unit="g", price=5.0, nutrition=None, **kw) -> Product:
    return Product(chain=chain, product_id=pid, name=name, size_value=size, size_unit=unit, price_chf=price, nutrition=nutrition, **kw)


def rec(ingredients, price=6.0, portions=1) -> Recipe:
    return Recipe(variant="schnell", name="T", description="d", portions=portions, cooking_minutes=20, equipment=["Herd"],
                  ingredients=ingredients, steps=["a", "b"], estimated_price_chf_per_portion=price,
                  estimated_macros_per_portion=Macros(kcal=900, carbs_g=100, protein_g=50, fat_g=25))


def test_proportional_cost_grams_pieces_and_cap():
    assert proportional_cost(200, prod(size=400, price=8.9), 1) == 4.45
    assert proportional_cost(60, prod(size=10, unit="Stk", price=3.65, name="Eier 10er"), 1, "Ei") == pytest.approx(3.65 * 60 / (10 * PIECE_WEIGHTS_G["ei"]), abs=0.01)
    assert proportional_cost(60, prod(size=6, unit="piece", price=3.3, name="Eier 53+"), 1, "Ei") == pytest.approx(3.3 * 60 / (6 * 60), abs=0.01)
    assert proportional_cost(900, prod(size=400, price=8.9), 1) == 8.9  # nie mehr als der Einkauf
    assert proportional_cost(100, prod(size=None, unit=None, price=4.0), 2) == 8.0


def test_shopping_list_packs_raised_and_estimates_for_missing():
    ings = [Ingredient(name="Poulet", grams=900, search_term="Pouletbrust", base_ingredient=False),
            Ingredient(name="Öl", grams=10, search_term="Olivenöl", base_ingredient=True)]
    r = rec(ings, price=7.0)
    p = prod(size=400, price=8.9, nutrition=Nutrition100g(kcal=105, carbs_g=0, protein_g=23, fat_g=1.2))
    chosen = {"Poulet": (ProductChoice(variant="schnell", ingredient="Poulet", chain="migros", product_id="1", packs=1, reason="ok"), p),
              "Öl": (ProductChoice(variant="schnell", ingredient="Öl", chain=None, product_id=None, packs=None, reason="nichts"), None)}
    sl = build_shopping_list(r, chosen)
    assert sl.lines[0].packs == 3 and any("auf 3 erhöht" in w for w in sl.warnings)
    assert sl.lines[0].total_chf == 26.7 and sl.lines[0].proportional_chf == pytest.approx(20.025, abs=0.01)
    assert sl.lines[1].estimated and sl.lines[1].proportional_chf == 0.3  # Mindestschätzung, Rest wäre negativ
    assert sl.macros_estimated  # Öl ohne Produkt → Modellschätzung


def test_macros_from_nutrition_when_complete():
    ings = [Ingredient(name="Reis", grams=100, search_term="Reis", base_ingredient=True),
            Ingredient(name="Poulet", grams=200, search_term="Pouletbrust", base_ingredient=False)]
    r = rec(ings, portions=2)
    reis = prod(pid="r", size=1000, price=3.0, nutrition=Nutrition100g(kcal=350, carbs_g=78, protein_g=8, fat_g=0.6))
    poulet = prod(pid="p", size=400, price=8.9, nutrition=Nutrition100g(kcal=105, carbs_g=0, protein_g=23, fat_g=1.2))
    chosen = {"Reis": (ProductChoice(variant="schnell", ingredient="Reis", chain="migros", product_id="r", packs=1, reason=""), reis),
              "Poulet": (ProductChoice(variant="schnell", ingredient="Poulet", chain="migros", product_id="p", packs=1, reason=""), poulet)}
    sl = build_shopping_list(r, chosen)
    assert not sl.macros_estimated
    assert sl.macros_per_portion == Macros(kcal=round((350 + 210) / 2), carbs_g=39, protein_g=27, fat_g=round((0.6 + 2.4) / 2))
    assert sl.price_per_portion_chf == pytest.approx((0.3 + 4.45) / 2, abs=0.01)


# --- checks ------------------------------------------------------------------------------------------------

def test_check_plan_budget_and_macros():
    plan = PlanResponse.model_validate(json.loads((FX / "plan_response.json").read_text()))
    target = {"kcal": 1120, "carbs_g": 131, "protein_g": 55, "fat_g": 42, "share_pct": 40}
    w = check_plan(plan, target)
    assert not any("fehlt" in x for x in w)
    assert not any("Protein" in x or "Fett" in x for x in w)  # mehr Protein / weniger Fett ist "besser", keine Warnung
    assert not any("kcal" in x for x in w)  # 1'000–1'100 kcal liegen innerhalb ±15 % von 1'120
    r = plan.by_variant("aufwendig").model_copy(update={"estimated_price_chf_per_portion": 11.5})
    plan2 = PlanResponse(recipes=[plan.by_variant("budget"), plan.by_variant("schnell"), r])
    assert any("für aufwendig erlaubt" in x for x in check_plan(plan2, target))
    b = plan.by_variant("budget").model_copy(update={"estimated_price_chf_per_portion": 11.5})
    plan3 = PlanResponse(recipes=[b, plan.by_variant("schnell"), plan.by_variant("aufwendig")])
    assert any("budget: 11.50 CHF/Portion über dem Maximum" in x for x in check_plan(plan3, target))


def test_check_plan_uses_real_prices_when_given():
    plan = PlanResponse.model_validate(json.loads((FX / "plan_response.json").read_text()))
    target = {"kcal": 1120, "carbs_g": 131, "protein_g": 55, "fat_g": 42, "share_pct": 40}
    ings = [Ingredient(name="A", grams=100, search_term="a", base_ingredient=False), Ingredient(name="B", grams=100, search_term="b", base_ingredient=True)]
    pa = prod(pid="a", size=100, price=11.0, estimated=True)
    chosen = {"A": (ProductChoice(variant="budget", ingredient="A", chain="migros", product_id="a", packs=1, reason=""), pa),
              "B": (ProductChoice(variant="budget", ingredient="B", chain=None, product_id=None, packs=None, reason=""), None)}
    sl = build_shopping_list(plan.by_variant("budget").model_copy(update={"ingredients": ings}), chosen)
    assert sl.price_per_portion_chf > 10
    w = check_plan(plan, target, {"budget": sl})
    assert any("budget: " in x and "(echt) über dem Maximum" in x for x in w)
    assert any("budget: ohne Produkt, geschätzt: B" in x for x in w) and any("budget: Preis aus Cache (geschätzt): A" in x for x in w)
    assert any("budget: echter Preis/Portion weicht +" in x for x in w)
    assert not any("schnell: " in x and "CHF/Portion" in x for x in w)  # ohne Liste gilt die Schätzung (6.80 CHF, im Ziel)


def test_macro_direction_rules():
    from fuelplan.checks import _macro_warnings
    target = {"kcal": 1000, "carbs_g": 100, "protein_g": 50, "fat_g": 40}
    assert _macro_warnings("x", Macros(kcal=1000, carbs_g=100, protein_g=80, fat_g=20), target) == []  # Protein/Fett "besser"
    assert len(_macro_warnings("x", Macros(kcal=1000, carbs_g=150, protein_g=50, fat_g=40), target)) == 1  # KH zu hoch warnt
    w = _macro_warnings("x", Macros(kcal=1300, carbs_g=70, protein_g=30, fat_g=60), target)
    assert len(w) == 4 and all("weicht" in x for x in w)
    assert _macro_warnings("x", Macros(kcal=700, carbs_g=100, protein_g=50, fat_g=40), target) == ["x: kcal 700 weicht -30% vom Abendessen-Ziel (1000) ab"]
    assert _macro_warnings("x", Macros(kcal=1100, carbs_g=90, protein_g=45, fat_g=45), target) == []  # innerhalb ±15 %


def test_check_shopping_flags_missing_cache_and_price():
    ings = [Ingredient(name="A", grams=100, search_term="a", base_ingredient=False), Ingredient(name="B", grams=100, search_term="b", base_ingredient=True)]
    r = rec(ings, price=6.0)
    pa = prod(pid="a", size=100, price=11.0, estimated=True)
    chosen = {"A": (ProductChoice(variant="schnell", ingredient="A", chain="migros", product_id="a", packs=1, reason=""), pa),
              "B": (ProductChoice(variant="schnell", ingredient="B", chain=None, product_id=None, packs=None, reason=""), None)}
    sl = build_shopping_list(r, chosen)
    w = check_shopping(sl, {"kcal": 900, "carbs_g": 100, "protein_g": 50, "fat_g": 25})
    assert any("Ohne Produkt, geschätzt: B" in x for x in w)
    assert any("Preis aus Cache (geschätzt): A" in x for x in w)
    assert any("über dem Maximum" in x for x in w) and any("weicht +" in x and "Schätzung" in x for x in w)


# --- dry-run / runlog ------------------------------------------------------------------------------------------

def test_dry_run_llm_plan_and_fixture_or_fallback_execute():
    llm = DryRunLLM()
    res = llm.complete_json(model="m", system="", user="", schema=PlanResponse, max_tokens=1)
    plan = res.data
    assert len(plan.recipes) == 3 and res.usage.cost_usd == 0 and res.usage.cost_source == "dry-run"
    products = {"Pouletbrust": MockBridge().search("Pouletbrust").products}
    iq = {r.variant: {i.name: "Pouletbrust" for i in r.ingredients} for r in plan.recipes}
    res2 = llm.complete_json(model="m", system="", user="", schema=ExecuteResponse, max_tokens=1,
                             hints={"plan": plan, "products": products, "ingredient_query": iq})
    choices = res2.data
    assert len(choices.choices) == sum(len(r.ingredients) for r in plan.recipes)
    # schnell passt zur Fixture (Zutatnamen gleich) → gespeicherte Wahl; budget/aufwendig → Ersatz günstigster Grundpreis
    assert all("Dry-Run" not in c.reason for c in choices.for_variant("schnell"))
    assert all("Dry-Run" in c.reason for c in choices.for_variant("budget") + choices.for_variant("aufwendig"))
    c = choices.for_variant("budget")[0]
    assert c.product_id and c.packs == 1 and c.variant == "budget"
    assert cheapest_choice("budget", "Y", 100, []).product_id is None
    with pytest.raises(ValueError):
        llm.complete_json(model="m", system="", user="", schema=ExecuteResponse, max_tokens=1)


def test_run_dir_create_latest_and_usage(tmp_path):
    from datetime import datetime
    from fuelplan.llm.client import Usage
    r1 = RunDir.create(tmp_path, now=datetime(2026, 11, 6, 14, 0))
    r2 = RunDir.create(tmp_path, now=datetime(2026, 11, 6, 14, 0))
    assert r1.name == "2026-11-06_1400" and r2.name == "2026-11-06_1400_2"
    assert RunDir.latest_with_plan(tmp_path) is None
    r1.write_json("plan_response.json", {})
    assert RunDir.latest_with_plan(tmp_path).name == r1.name
    r1.add_usage(Usage(model="m", label="plan", input_tokens=10, output_tokens=5, cost_usd=0.01, cost_source="openrouter"))
    r1.add_usage(Usage(model="m", label="execute", input_tokens=10, output_tokens=5, cost_usd=0.02, cost_source="openrouter"))
    u = r1.read_json("usage.json")
    assert u["total_cost_usd"] == pytest.approx(0.03) and u["total_tokens"] == 30 and len(u["calls"]) == 2
    assert (tmp_path / "llm_usage.jsonl").read_text().count("\n") == 2
