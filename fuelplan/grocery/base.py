"""GroceryBridge-Schnittstelle und Product-Datenklasse.

Regeln aus Phase 0, die hier im Code gelten: nur die Ketten aus config.GROCERY_CHAINS,
kleines Limit pro Kette, maximal config.MAX_GROCERY_QUERIES_PER_RUN Abfragen pro Lauf,
keine Sortiments-Durchsuchung (kein Offset/Paginieren). Coop ausschliesslich über swissgroceries.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from fuelplan import config

Chain = Literal["migros", "denner", "coop"]


class Nutrition100g(BaseModel):
    """Nährwerte pro 100 g, falls die Quelle sie liefert."""

    kcal: float | None = None
    carbs_g: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None


class Product(BaseModel):
    chain: Chain
    product_id: str
    name: str
    brand: str | None = None
    size_value: float | None = None  # Packungsgrösse, z. B. 500
    size_unit: str | None = None  # g, kg, ml, l, Stk
    price_chf: float  # aktueller Preis pro Packung
    regular_price_chf: float | None = None  # Normalpreis, wenn gerade Aktion
    unit_price_chf: float | None = None  # Grundpreis
    unit_price_per: str | None = None  # z. B. "kg", "l", "100g"
    promotion: bool = False
    promotion_until: date | None = None
    promotion_text: str | None = None
    nutrition: Nutrition100g | None = None
    estimated: bool = False  # Preis aus Cache/Schätzung → in der Ausgabe "(geschätzt)"
    note: str | None = None  # z. B. "Preis per 100 g, Packungspreis gerechnet"
    price_date: date | None = None  # wann der Preis abgefragt wurde

    @property
    def is_pieces(self) -> bool:
        """Stückware: Einheit Stk/Stück/piece(s)/pc (Migros liefert z. B. "6 piece")."""
        u = (self.size_unit or "").lower().strip()
        return u in ("stk", "stk.", "stück", "st", "piece", "pieces", "pc", "pcs", "x")

    @property
    def size_g(self) -> float | None:
        """Packungsgrösse in Gramm bzw. Millilitern (1 ml ≈ 1 g), None wenn unbekannt oder Stück."""
        if self.size_value is None or not self.size_unit:
            return None
        u = self.size_unit.lower()
        if u in ("g", "ml"):
            return self.size_value
        if u in ("kg", "l"):
            return self.size_value * 1000
        return None

    @property
    def size_text(self) -> str:
        if self.size_value is None or not self.size_unit:
            return "–"
        v = f"{self.size_value:g}".replace(".", ",")
        return f"{v} Stk" if self.is_pieces else f"{v} {self.size_unit}"


class SearchResult(BaseModel):
    """Treffer einer Abfrage pro Kette plus Fehler (Kette ohne Antwort) und Datenstand."""

    query: str
    products: list[Product] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)  # chain → Grund
    from_cache: dict[str, bool] = Field(default_factory=dict)  # chain → swissgroceries-Cache

    def by_chain(self, chain: Chain) -> list[Product]:
        return [p for p in self.products if p.chain == chain]


class QueryBudgetExceeded(RuntimeError):
    """Mehr Supermarkt-Abfragen als pro Lauf erlaubt."""


class GroceryBridge(ABC):
    """Schnittstelle für Mock und swissgroceries. Zählt Abfragen und erzwingt das Limit pro Lauf."""

    def __init__(self, max_queries: int = config.MAX_GROCERY_QUERIES_PER_RUN) -> None:
        self.max_queries = max_queries
        self.queries_made = 0
        self.log: list[str] = []

    def search(self, query: str, chains: tuple[Chain, ...] = config.GROCERY_CHAINS,
               limit: int = config.GROCERY_SEARCH_LIMIT) -> SearchResult:
        q = query.strip()
        if not q:
            raise ValueError("Leerer Suchbegriff.")
        bad = [c for c in chains if c not in config.GROCERY_CHAINS]
        if bad:
            raise ValueError(f"Kette nicht erlaubt: {bad} (erlaubt: {config.GROCERY_CHAINS})")
        if self.queries_made >= self.max_queries:
            raise QueryBudgetExceeded(f"Limit von {self.max_queries} Supermarkt-Abfragen pro Lauf erreicht (bei „{q}“).")
        self.queries_made += 1
        self.log.append(q)
        return self._search(q, tuple(chains), min(limit, config.GROCERY_SEARCH_LIMIT))

    @abstractmethod
    def _search(self, query: str, chains: tuple[Chain, ...], limit: int) -> SearchResult: ...

    def close(self) -> None:  # pragma: no cover - Mock braucht nichts
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
