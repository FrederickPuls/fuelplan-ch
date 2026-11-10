"""JSON-Schemas (pydantic) für die strukturierten Antworten.

Schritt 5: Abnahme-Schema. Schritt 6: PlanResponse (3 Rezepte) und ExecuteResponse (Produktwahl).
Schritt 10: ExecuteResponse umfasst alle drei Varianten (ProductChoice.variant), ein Aufruf pro Lauf.
Die Schemas gehen als `output_config.format` (json_schema) mit; die Antwort wird mit pydantic validiert.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AcceptanceIngredient(BaseModel):
    name: str = Field(description="Zutat auf Deutsch")
    grams: int = Field(ge=1, description="Menge in Gramm für 1 Portion")
    search_term: str = Field(description="Suchbegriff für den Supermarkt, z. B. 'Pouletbrust'")


class AcceptanceRecipeIdea(BaseModel):
    """Kleines Schema für den Abnahme-Aufruf in Schritt 5."""

    name: str
    cooking_minutes: int = Field(ge=1, le=180)
    ingredients: list[AcceptanceIngredient] = Field(min_length=2, max_length=8)
    estimated_price_chf: float = Field(ge=0)
    note: str = Field(description="Ein Satz, warum das Rezept zum Tag passt")


# --- Schritt 6: Plan (LLM-Aufruf 1) ------------------------------------------------------------

Variant = Literal["budget", "schnell", "aufwendig"]
VARIANTS: tuple[str, ...] = ("budget", "schnell", "aufwendig")


class Macros(BaseModel):
    kcal: int = Field(ge=0)
    carbs_g: int = Field(ge=0)
    protein_g: int = Field(ge=0)
    fat_g: int = Field(ge=0)


class Ingredient(BaseModel):
    name: str = Field(description="Zutat auf Deutsch, z. B. 'Pouletbrust'")
    grams: int = Field(ge=1, description="Menge in Gramm für die angegebene Portionenzahl (Stückware in Gramm umrechnen, 1 Ei ≈ 60 g)")
    search_term: str = Field(description="Kurzer Suchbegriff für den Supermarkt, 1–3 Wörter, z. B. 'Basmati Reis'")
    base_ingredient: bool = Field(description="true für Vorrats-/Basiszutaten (Reis, Pasta, Öl, Gewürze, Sojasauce), die nicht täglich gekauft werden")


class Recipe(BaseModel):
    variant: Variant
    name: str
    description: str = Field(description="Ein bis zwei Sätze")
    portions: int = Field(ge=1, le=6, description="1, oder mehr bei Vorkochen")
    cooking_minutes: int = Field(ge=5, le=180)
    equipment: list[str] = Field(description="Geräte aus der Küche des Nutzers")
    ingredients: list[Ingredient] = Field(min_length=2, max_length=15)
    steps: list[str] = Field(min_length=2, max_length=12)
    estimated_price_chf_per_portion: float = Field(ge=0)
    estimated_macros_per_portion: Macros


class PlanResponse(BaseModel):
    recipes: list[Recipe] = Field(min_length=3, max_length=3, description="Genau eine Variante budget, eine schnell, eine aufwendig")

    @model_validator(mode="after")
    def _one_per_variant(self) -> "PlanResponse":
        got = sorted(r.variant for r in self.recipes)
        if got != sorted(VARIANTS):
            raise ValueError(f"Varianten müssen genau {VARIANTS} sein, erhalten: {got}")
        return self

    def by_variant(self, variant: str) -> Recipe:
        return next(r for r in self.recipes if r.variant == variant)


# --- Schritt 6/10: Execute (LLM-Aufruf 2, alle drei Varianten) ---------------------------------

class ProductChoice(BaseModel):
    """Reihenfolge der Felder ist Absicht: erst die Begründung (nennt das gewählte Produkt), dann chain/product_id/packs.
    Beim ersten Haiku-Lauf stand die ID des billigsten Produkts vor einer Begründung, die ein anderes Produkt nannte."""

    variant: Variant = Field(description="Variante, zu der die Zutat gehört (budget, schnell, aufwendig)")
    ingredient: str = Field(description="Zutatname genau wie in der Liste der Variante")
    reason: str = Field(description="Kurze Begründung, max. 1 Satz; nennt das gewählte Produkt mit Namen, oder warum kein Produkt passt")
    chain: Literal["migros", "denner", "coop"] | None = Field(description="Laden des in der Begründung genannten Produkts; null, wenn kein passendes Produkt")
    product_id: str | None = Field(description="Produkt-ID genau dieses Produkts aus der Trefferliste, null wenn kein passendes Produkt")
    packs: int | None = Field(ge=1, description="Anzahl Packungen, null wenn kein Produkt")


class ExecuteResponse(BaseModel):
    choices: list[ProductChoice] = Field(min_length=1, description="Eine Wahl pro Variante und Zutat")

    def for_variant(self, variant: str) -> list[ProductChoice]:
        return [c for c in self.choices if c.variant == variant]

    @property
    def variants(self) -> set[str]:
        return {c.variant for c in self.choices}
