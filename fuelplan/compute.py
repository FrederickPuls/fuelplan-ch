"""Rechnen in Python (Schritt 6 „Compute“ des Ablaufs): Preise, Packungen, Summen, Makros.

- Einkaufspreis = ganze Packungen × Packungspreis.
- Preis pro Portion = anteilige Menge (benötigte Gramm / Packungsgrösse × Preis) / Portionen;
  Stückware (Packung in "Stk") wird über ein angenommenes Stückgewicht (PIECE_WEIGHTS_G, sonst
  DEFAULT_PIECE_G) anteilig gerechnet, höchstens der volle Packungspreis.
- Zutaten ohne Produkt bekommen einen Schätzanteil: Rest der Modellschätzung, mindestens
  ESTIMATE_MIN_CHF pro fehlender Zutat; alles mit "(geschätzt)" markiert.
- Makros pro Portion aus den Nährwerten pro 100 g, wenn alle Zutaten Nährwerte haben; sonst
  die Schätzung des Modells, markiert "(geschätzt)".
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from fuelplan.grocery.base import Product
from fuelplan.llm.schemas import Macros, ProductChoice, Recipe

ESTIMATE_MIN_CHF = 0.30  # pro Zutat ohne Produkt (Gewürze, Öl aus dem Vorrat …)
# Annahmen für Stückware (Gramm pro Stück), Schlüsselwort im Zutat- oder Produktnamen (klein)
PIECE_WEIGHTS_G = {"ei": 60, "avocado": 170, "zitrone": 100, "limette": 70, "banane": 120, "zwiebel": 100, "knoblauch": 50,
                   "peperoni": 180, "tortilla": 60, "wrap": 60, "brötchen": 60}
DEFAULT_PIECE_G = 100


def piece_weight_g(*names: str) -> int:
    text = " ".join(n.lower() for n in names)
    for key, g in PIECE_WEIGHTS_G.items():
        if key in text:
            return g
    return DEFAULT_PIECE_G


def proportional_cost(grams: int, product: Product, packs: int, ingredient_name: str = "") -> float:
    """Anteilige Kosten der benötigten Menge; nie mehr als der Einkaufspreis der Packungen."""
    total = product.price_chf * packs
    if product.size_g:
        return round(min(total, product.price_chf * grams / product.size_g), 2)
    if product.size_value and product.is_pieces:
        pack_g = product.size_value * piece_weight_g(ingredient_name, product.name)
        return round(min(total, product.price_chf * grams / pack_g), 2)
    return round(total, 2)


class ShoppingLine(BaseModel):
    ingredient: str
    grams: int
    product: Product | None = None
    packs: int = 0
    price_each_chf: float = 0.0
    total_chf: float = 0.0  # Einkaufspreis (ganze Packungen)
    proportional_chf: float = 0.0  # anteilige Kosten für das Rezept (alle Portionen)
    estimated: bool = False  # Preis geschätzt (kein Produkt oder Cache-Preis)
    promotion: bool = False
    note: str | None = None
    reason: str = ""


class ShoppingList(BaseModel):
    variant: str
    recipe_name: str
    portions: int
    lines: list[ShoppingLine]
    total_chf: float  # Summe Einkauf (ganze Packungen)
    proportional_total_chf: float  # anteilige Kosten des Rezepts
    price_per_portion_chf: float
    estimated_price_per_portion_chf: float  # Schätzung des Modells aus Teil A
    estimated_share_chf: float = 0.0  # Anteil der geschätzten Zutaten an proportional_total
    has_estimates: bool = False
    macros_per_portion: Macros
    macros_estimated: bool  # True = Schätzung des Modells, False = aus Nährwerten gerechnet
    promotions: int = 0
    warnings: list[str] = Field(default_factory=list)

    @property
    def deviation_chf(self) -> float:
        return round(self.price_per_portion_chf - self.estimated_price_per_portion_chf, 2)


def packs_needed(grams: int, product: Product) -> int:
    return max(1, math.ceil(grams / product.size_g)) if product.size_g else 1


def build_shopping_list(recipe: Recipe, chosen: dict[str, tuple[ProductChoice, Product | None]]) -> ShoppingList:
    lines: list[ShoppingLine] = []
    warnings: list[str] = []
    for ing in recipe.ingredients:
        choice, product = chosen.get(ing.name, (None, None))
        if product is None:
            lines.append(ShoppingLine(ingredient=ing.name, grams=ing.grams, estimated=True,
                                      reason=choice.reason if choice else "kein Produkt"))
            continue
        packs = choice.packs or 1
        need = packs_needed(ing.grams, product)
        note = product.note
        if packs < need:
            warnings.append(f"{ing.name}: {packs} Packung(en) à {product.size_text} reichen nicht für {ing.grams} g, auf {need} erhöht")
            packs = need
        total = round(product.price_chf * packs, 2)
        proportional = proportional_cost(ing.grams, product, packs, ing.name)
        lines.append(ShoppingLine(ingredient=ing.name, grams=ing.grams, product=product, packs=packs,
                                  price_each_chf=product.price_chf, total_chf=total, proportional_chf=proportional,
                                  estimated=product.estimated, promotion=product.promotion, note=note, reason=choice.reason))

    found_prop = sum(l.proportional_chf for l in lines if l.product is not None)
    missing = [l for l in lines if l.product is None]
    est_total_all_portions = recipe.estimated_price_chf_per_portion * recipe.portions
    estimated_share = 0.0
    if missing:
        remainder = est_total_all_portions - found_prop
        estimated_share = round(max(remainder, ESTIMATE_MIN_CHF * len(missing)), 2)
        per_missing = round(estimated_share / len(missing), 2)
        for l in missing:
            l.proportional_chf = per_missing
    proportional_total = round(found_prop + estimated_share, 2)
    total = round(sum(l.total_chf for l in lines), 2)

    macros, macros_estimated = compute_macros(recipe, lines)
    return ShoppingList(
        variant=recipe.variant, recipe_name=recipe.name, portions=recipe.portions, lines=lines,
        total_chf=total, proportional_total_chf=proportional_total,
        price_per_portion_chf=round(proportional_total / recipe.portions, 2),
        estimated_price_per_portion_chf=recipe.estimated_price_chf_per_portion,
        estimated_share_chf=estimated_share, has_estimates=any(l.estimated for l in lines),
        macros_per_portion=macros, macros_estimated=macros_estimated,
        promotions=sum(1 for l in lines if l.promotion), warnings=warnings,
    )


def compute_macros(recipe: Recipe, lines: list[ShoppingLine]) -> tuple[Macros, bool]:
    """Aus Nährwerten pro 100 g, wenn jede Zutat ein Produkt mit Nährwerten hat; sonst Modellschätzung."""
    kcal = carbs = protein = fat = 0.0
    for l in lines:
        n = l.product.nutrition if l.product else None
        if n is None or n.kcal is None:
            return recipe.estimated_macros_per_portion, True
        f = l.grams / 100
        kcal += n.kcal * f
        carbs += (n.carbs_g or 0) * f
        protein += (n.protein_g or 0) * f
        fat += (n.fat_g or 0) * f
    p = recipe.portions
    return Macros(kcal=round(kcal / p), carbs_g=round(carbs / p), protein_g=round(protein / p), fat_g=round(fat / p)), False
