"""Preis-Cache für Basiszutaten (Reis, Pasta, Haferflocken, Öl, Gewürze …).

Basiszutaten werden nicht täglich neu abgefragt: Liegt ein Preis jünger als
config.PRICE_CACHE_MAX_AGE_DAYS vor, kommt er aus dem Cache und wird in der Ausgabe
mit "(geschätzt)" markiert. Datei: config.PRICE_CACHE_FILE (gitignored).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from fuelplan import config
from fuelplan.grocery.base import Product

# Suchbegriffe (klein, Teilwort reicht), die als Basiszutat gelten
BASE_INGREDIENT_KEYWORDS = (
    "reis", "pasta", "spaghetti", "penne", "fusilli", "nudeln", "hörnli", "haferflocken", "mehl",
    "olivenöl", "rapsöl", "öl", "butter", "salz", "pfeffer", "gewürz", "paprika", "curry", "kreuzkümmel",
    "zimt", "oregano", "zucker", "honig", "essig", "sojasauce", "bouillon", "brühe", "tomatenmark",
    "kokosmilch", "linsen", "kichererbsen", "bohnen", "mais", "couscous", "bulgur", "quinoa", "polenta",
    "knoblauch", "zwiebel", "kartoffel", "thunfisch", "pesto", "senf", "ketchup", "erdnussbutter",
)


def is_base_ingredient(query: str) -> bool:
    q = query.lower()
    return any(k in q for k in BASE_INGREDIENT_KEYWORDS)


class PriceCache:
    def __init__(self, path: Path = config.PRICE_CACHE_FILE, max_age_days: int = config.PRICE_CACHE_MAX_AGE_DAYS,
                 today: date | None = None) -> None:
        self.path = Path(path)
        self.max_age = timedelta(days=max_age_days)
        self.today = today or config.today()
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def _key(query: str) -> str:
        return " ".join(query.lower().split())

    def get(self, query: str) -> list[Product] | None:
        """Produkte aus dem Cache, als geschätzt markiert; None, wenn nicht vorhanden oder zu alt."""
        entry = self._data.get(self._key(query))
        if not entry:
            return None
        cached = date.fromisoformat(entry["date"])
        if self.today - cached > self.max_age:
            return None
        return [Product(**p).model_copy(update={"estimated": True, "price_date": cached}) for p in entry["products"]]

    def put(self, query: str, products: list[Product]) -> None:
        if not products:
            return
        self._data[self._key(query)] = {
            "date": self.today.isoformat(),
            "products": [p.model_dump(mode="json", exclude={"estimated"}) for p in products],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")

    def age_days(self, query: str) -> int | None:
        entry = self._data.get(self._key(query))
        return (self.today - date.fromisoformat(entry["date"])).days if entry else None
