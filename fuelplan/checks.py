"""Prüfungen in Python: Execute-Antwort gegen die gelieferten Produkte, pro Variante (Schritt 6/10);
Budget, Makros ±15 %, Vollständigkeit und "(geschätzt)" (Schritt 7). Seit Schritt 10 prüft Teil A den
Budget-Rahmen auf den echten Preis pro Portion aller drei Varianten. Verstösse werden als Warnungen oben
in der Ausgabe gezeigt, der Lauf bricht dafür nicht ab.
"""

from __future__ import annotations

from fuelplan.grocery.base import Product
from fuelplan.llm.schemas import ExecuteResponse, ProductChoice, Recipe


def validate_execute_choices(recipe: Recipe, response: ExecuteResponse,
                             products: dict[str, list[Product]]) -> tuple[dict[str, tuple[ProductChoice, Product | None]], list[str]]:
    """Ordnet jeder Zutat der Variante die gewählte Produktwahl zu und prüft, dass IDs aus den Treffern stammen.

    Nur die Wahlen mit `variant == recipe.variant` zählen (ein Execute-Aufruf deckt alle drei Varianten ab).
    products: Zutatname → Treffer dieser Variante. Rückgabe: {Zutat: (Wahl, Produkt|None)} und Warnungen
    (ungültige ID → Wahl wird auf null gesetzt).
    """
    warnings: list[str] = []
    by_name = {c.ingredient: c for c in response.for_variant(recipe.variant)}
    v = recipe.variant
    result: dict[str, tuple[ProductChoice, Product | None]] = {}
    for ing in recipe.ingredients:
        choice = by_name.get(ing.name)
        if choice is None:
            warnings.append(f"{ing.name}: keine Wahl in der Antwort")
            result[ing.name] = (ProductChoice(variant=v, ingredient=ing.name, chain=None, product_id=None, packs=None, reason="fehlt in Antwort"), None)
            continue
        if choice.product_id is None or choice.chain is None:
            result[ing.name] = (choice, None)
            continue
        hits = [p for p in products.get(ing.name, []) if p.product_id == choice.product_id and p.chain == choice.chain]
        if not hits:
            warnings.append(f"{ing.name}: Produkt-ID {choice.product_id} ({choice.chain}) nicht in den Treffern – verworfen")
            result[ing.name] = (choice.model_copy(update={"chain": None, "product_id": None, "packs": None, "reason": f"ungültige ID verworfen: {choice.reason}"}), None)
            continue
        if not choice.packs or choice.packs < 1:
            warnings.append(f"{ing.name}: Packungszahl fehlt, auf 1 gesetzt")
            choice = choice.model_copy(update={"packs": 1})
        result[ing.name] = (choice, hits[0])
    extra = set(by_name) - {i.name for i in recipe.ingredients}
    if extra:
        warnings.append(f"Antwort enthält unbekannte Zutaten: {sorted(extra)}")
    return result, warnings


# --- Schritt 7: Budget, Makros, Vollständigkeit, "(geschätzt)" ----------------------------------

from fuelplan.compute import ShoppingList  # noqa: E402
from fuelplan.llm.schemas import PlanResponse, VARIANTS  # noqa: E402

BUDGET_MAX_CHF = 10.0
BUDGET_TARGET_CHF = (6.0, 7.0)
MACRO_TOLERANCE = 0.15


# Richtung der Makro-Prüfung (Entscheidung 06.11.2026): kcal und KH dürfen nicht stark abweichen (beide
# Richtungen); Protein warnt nur, wenn es UNTER dem Ziel liegt, Fett nur, wenn es DARÜBER liegt – mehr Protein
# und weniger Fett gelten als "besser".
MACRO_RULES = {
    "kcal": ("kcal", "both"),
    "carbs_g": ("KH", "both"),
    "protein_g": ("Protein", "below"),
    "fat_g": ("Fett", "above"),
}


def _macro_warnings(label: str, got, target: dict[str, int]) -> list[str]:
    out = []
    for key, (name, direction) in MACRO_RULES.items():
        t = target.get(key)
        g = getattr(got, key)
        if not t:
            continue
        dev = (g - t) / t
        if abs(dev) <= MACRO_TOLERANCE:
            continue
        if direction == "below" and dev > 0:
            continue
        if direction == "above" and dev < 0:
            continue
        unit = "" if key == "kcal" else " g"
        out.append(f"{label}: {name} {g}{unit} weicht {dev:+.0%} vom Abendessen-Ziel ({t}{unit}) ab")
    return out


def check_plan(plan: PlanResponse, dinner_target: dict[str, int], real: dict[str, ShoppingList] | None = None) -> list[str]:
    """Warnungen für Teil A: alle Varianten, Preis/Portion ≤ 10 CHF (aufwendig: ausweisen), Makros ±15 %.

    real: Variante → ShoppingList aus Teil A (Schritt 10). Dann gilt der Budget-Check für den echten Preis pro
    Portion, dazu Hinweise zu fehlenden Produkten, Cache-Preisen und grosser Abweichung zur Schätzung.
    Makros bleiben die Schätzung des Modells (Abweichung 7.5).
    """
    warnings: list[str] = []
    real = real or {}
    have = {r.variant for r in plan.recipes}
    for v in VARIANTS:
        if v not in have:
            warnings.append(f"Variante {v} fehlt")
    for r in plan.recipes:
        sl = real.get(r.variant)
        price = sl.price_per_portion_chf if sl else r.estimated_price_chf_per_portion
        tag = " (echt)" if sl else ""
        if price > BUDGET_MAX_CHF:
            if r.variant == "aufwendig":
                warnings.append(f"aufwendig: {price:.2f} CHF/Portion{tag} liegt über dem Maximum von {BUDGET_MAX_CHF:.0f} CHF (für aufwendig erlaubt, ausgewiesen)")
            else:
                warnings.append(f"{r.variant}: {price:.2f} CHF/Portion{tag} über dem Maximum von {BUDGET_MAX_CHF:.0f} CHF")
        elif price > BUDGET_TARGET_CHF[1] and r.variant != "aufwendig":
            warnings.append(f"{r.variant}: {price:.2f} CHF/Portion{tag} über dem Ziel von {BUDGET_TARGET_CHF[0]:.0f}–{BUDGET_TARGET_CHF[1]:.0f} CHF")
        if sl:
            missing = [l.ingredient for l in sl.lines if l.product is None]
            if missing:
                warnings.append(f"{r.variant}: ohne Produkt, geschätzt: {', '.join(missing)}")
            cached = [l.ingredient for l in sl.lines if l.product is not None and l.estimated]
            if cached:
                warnings.append(f"{r.variant}: Preis aus Cache (geschätzt): {', '.join(cached)}")
            if abs(sl.deviation_chf) >= 2.0:
                warnings.append(f"{r.variant}: echter Preis/Portion weicht {sl.deviation_chf:+.2f} CHF von der Schätzung ({sl.estimated_price_per_portion_chf:.2f}) ab")
        warnings += _macro_warnings(r.variant, r.estimated_macros_per_portion, dinner_target)
    return warnings


def check_shopping(sl: ShoppingList, dinner_target: dict[str, int]) -> list[str]:
    """Warnungen für Teil B: jede Zutat hat Produkt oder ist geschätzt, Preis/Portion, Makros."""
    warnings: list[str] = list(sl.warnings)
    missing = [l.ingredient for l in sl.lines if l.product is None]
    if missing:
        warnings.append(f"Ohne Produkt, geschätzt: {', '.join(missing)}")
    cached = [l.ingredient for l in sl.lines if l.product is not None and l.estimated]
    if cached:
        warnings.append(f"Preis aus Cache (geschätzt): {', '.join(cached)}")
    price = sl.price_per_portion_chf
    if price > BUDGET_MAX_CHF:
        suffix = " (für aufwendig erlaubt, ausgewiesen)" if sl.variant == "aufwendig" else ""
        warnings.append(f"Preis pro Portion {price:.2f} CHF über dem Maximum von {BUDGET_MAX_CHF:.0f} CHF{suffix}")
    if abs(sl.deviation_chf) >= 2.0:
        warnings.append(f"Echter Preis/Portion weicht {sl.deviation_chf:+.2f} CHF von der Schätzung ({sl.estimated_price_per_portion_chf:.2f}) ab")
    warnings += _macro_warnings("Abendessen", sl.macros_per_portion, dinner_target)
    return warnings
