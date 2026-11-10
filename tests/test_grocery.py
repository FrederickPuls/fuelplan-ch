"""Supermarkt-Bridge: Mock, Abbildung der swissgroceries-Antwort, Limits, Preis-Cache."""

from __future__ import annotations

from datetime import date

import pytest

from fuelplan import config
from fuelplan.grocery.base import GroceryBridge, Product, QueryBudgetExceeded, SearchResult
from fuelplan.grocery.mock import MockBridge
from fuelplan.grocery.price_cache import PriceCache, is_base_ingredient
from fuelplan.grocery.swissgroceries import load_store_ids, map_product, parse_search_result

COOP_RAW = {"chain": "coop", "id": "6675160", "name": "Broccoli ca. 500g", "size": {"value": 500, "unit": "g"},
            "price": {"current": 2.1, "regular": 2.85, "currency": "CHF"}, "unitPrice": {"value": 4.2, "per": "kg"},
            "tags": [], "promotion": {}}
MIGROS_RAW = {"chain": "migros", "id": "275704701000", "name": "Migros Broccoli", "brand": "Migros",
              "size": {"value": 1, "unit": "kg"}, "price": {"current": 4.8, "currency": "CHF"},
              "unitPrice": {"value": 4.8, "per": "kg"}}
ZERO_PRICE_RAW = {**MIGROS_RAW, "id": "x", "price": {"current": 0, "currency": "CHF"}}


# --- Mock ---------------------------------------------------------------------------------------

def test_mock_finds_products_per_chain_with_limit():
    b = MockBridge()
    r = b.search("Basmati Reis", limit=5)
    assert {p.chain for p in r.products} == {"migros", "denner", "coop"}
    assert all(p.price_chf > 0 and p.size_g == 1000 for p in r.products)
    assert r.errors == {}
    r2 = b.search("Pouletbrust", chains=("migros",), limit=1)
    assert len(r2.products) == 1 and r2.products[0].chain == "migros"


def test_mock_unknown_ingredient_gives_no_products_but_no_error():
    r = MockBridge().search("Drachenfrucht")
    assert r.products == [] and r.errors == {}


def test_mock_failing_chain_reports_error():
    r = MockBridge(failing_chains=("coop",)).search("Eier")
    assert "coop" in r.errors and r.by_chain("coop") == []
    assert r.by_chain("migros")


def test_mock_catalog_has_enough_ingredients():
    b = MockBridge()
    assert len({e[1].name for e in b._entries}) >= 60
    assert all(e[1].nutrition and e[1].nutrition.kcal is not None for e in b._entries)


# --- Limits ------------------------------------------------------------------------------------

def test_query_budget_enforced():
    b = MockBridge(max_queries=2)
    b.search("Reis"); b.search("Eier")
    with pytest.raises(QueryBudgetExceeded):
        b.search("Tofu")
    assert b.queries_made == 2 and b.log == ["Reis", "Eier"]


def test_only_allowed_chains_and_limit_capped():
    b = MockBridge()
    with pytest.raises(ValueError):
        b.search("Reis", chains=("aldi",))
    r = b.search("Reis", limit=50)
    assert all(len(r.by_chain(c)) <= config.GROCERY_SEARCH_LIMIT for c in config.GROCERY_CHAINS)
    with pytest.raises(ValueError):
        b.search("   ")


# --- Abbildung swissgroceries ---------------------------------------------------------------

def test_map_product_coop_promotion_from_regular_price():
    p = map_product(COOP_RAW, price_date=date(2026, 11, 6))
    assert p.chain == "coop" and p.product_id == "6675160"
    assert p.price_chf == 2.1 and p.regular_price_chf == 2.85 and p.promotion
    assert p.size_value == 500 and p.size_unit == "g" and p.size_g == 500
    assert p.unit_price_chf == 4.2 and p.unit_price_per == "kg"
    assert p.nutrition is None and p.estimated is False and p.price_date == date(2026, 11, 6)


def test_map_product_migros_no_promotion():
    p = map_product(MIGROS_RAW)
    assert p.brand == "Migros" and not p.promotion and p.regular_price_chf is None and p.size_g == 1000


DENNER_PROMO_RAW = {"chain": "denner", "id": "65d1b45c", "name": "Denner Pouletbrustmedaillons", "size": {"value": 300, "unit": "g"},
                    "price": {"current": 1.48, "currency": "CHF"}, "unitPrice": {"value": 4.93, "per": "kg"},
                    "promotion": {"endsAt": "2026-11-08", "description": "Ungarn, ca. 300 g, per 100 g"}}


def test_map_product_denner_promotion_per_100g_converted_to_pack_price():
    p = map_product(DENNER_PROMO_RAW)
    assert p.promotion and p.promotion_until == date(2026, 11, 8) and "per 100 g" in p.promotion_text
    assert p.price_chf == 4.44  # 1.48 CHF per 100 g × 300 g
    assert p.unit_price_chf == 14.8 and p.unit_price_per == "kg"
    assert p.note and "gerechnet" in p.note


def test_map_product_promotion_with_pack_price_unchanged():
    raw = {**DENNER_PROMO_RAW, "price": {"current": 4.5}, "promotion": {"endsAt": "2026-11-08", "description": "Aktion"}}
    p = map_product(raw)
    assert p.price_chf == 4.5 and p.promotion and p.note is None


def test_map_product_skips_zero_price_and_foreign_chain():
    assert map_product(ZERO_PRICE_RAW) is None
    assert map_product({**MIGROS_RAW, "chain": "aldi"}) is None


def test_parse_search_result_errors_and_missing_chain():
    data = {"byChain": {"coop": [COOP_RAW], "migros": [MIGROS_RAW, ZERO_PRICE_RAW], "denner": []},
            "errors": [{"chain": "denner", "code": "bot_protection", "reason": "DataDome"}],
            "sources": {"coop": {"fromCache": True}, "migros": {"fromCache": False}}}
    r = parse_search_result("Broccoli", data, ("migros", "denner", "coop"))
    assert [p.chain for p in r.products] == ["migros", "coop"]
    assert r.errors == {"denner": "bot_protection: DataDome"}
    assert r.from_cache == {"migros": False, "denner": False, "coop": True}
    r2 = parse_search_result("x", {"byChain": {"migros": []}}, ("migros", "coop"))
    assert r2.errors["coop"] == "keine Antwort" and "migros" not in r2.errors


def test_store_ids_file_has_all_three_chains():
    ids = load_store_ids()
    assert set(ids) == {"migros", "denner", "coop"} and all(ids.values())


# --- Product ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,unit,expected", [(500, "g", 500), (1, "kg", 1000), (400, "ml", 400), (1, "l", 1000), (6, "Stk", None), (None, None, None)])
def test_size_g(value, unit, expected):
    p = Product(chain="migros", product_id="1", name="x", price_chf=1.0, size_value=value, size_unit=unit)
    assert p.size_g == expected


@pytest.mark.parametrize("unit,pieces,text", [("Stk", True, "6 Stk"), ("piece", True, "6 Stk"), ("pieces", True, "6 Stk"), ("g", False, "6 g")])
def test_pieces_detection_and_size_text(unit, pieces, text):
    p = Product(chain="migros", product_id="1", name="Eier", price_chf=3.3, size_value=6, size_unit=unit)
    assert p.is_pieces is pieces and p.size_text == text


# --- Preis-Cache --------------------------------------------------------------------------------

def test_base_ingredient_detection():
    assert is_base_ingredient("Basmati Reis") and is_base_ingredient("Olivenöl") and is_base_ingredient("Spaghetti")
    assert not is_base_ingredient("Pouletbrust") and not is_base_ingredient("Broccoli")


def test_price_cache_roundtrip_marks_estimated_and_expires(tmp_path):
    path = tmp_path / "cache.json"
    products = MockBridge().search("Reis").products
    c = PriceCache(path, max_age_days=14, today=date(2026, 11, 6))
    assert c.get("Reis") is None
    c.put("Reis", products)
    got = PriceCache(path, max_age_days=14, today=date(2026, 11, 10)).get("  reis ")
    assert got and all(p.estimated and p.price_date == date(2026, 11, 6) for p in got)
    assert [p.price_chf for p in got] == [p.price_chf for p in products]
    assert PriceCache(path, max_age_days=14, today=date(2026, 11, 21)).get("Reis") is None
    assert PriceCache(path, today=date(2026, 11, 21)).age_days("Reis") == 15
    c.put("Leer", [])
    assert c.get("Leer") is None
