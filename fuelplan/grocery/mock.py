"""MockBridge: Fixture-Produkte aus tests/fixtures/mock_products.json. Standard in Tests und bei --mock."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fuelplan import config
from fuelplan.grocery.base import Chain, GroceryBridge, Product, SearchResult

MOCK_PRODUCTS_FILE = config.ROOT / "tests" / "fixtures" / "mock_products.json"


def _match(word: str, keyword: str) -> bool:
    """Exakt, oder Teilwort in beide Richtungen, aber nur wenn beide mindestens 4 Zeichen haben (sonst trifft „ei“ auf „Reis“)."""
    if word == keyword:
        return True
    return len(word) >= 4 and len(keyword) >= 4 and (word in keyword or keyword in word)


class MockBridge(GroceryBridge):
    """Sucht im Fixture-Katalog: Treffer, wenn der Suchbegriff (oder ein Teilwort) in den Produkt-Schlüsselwörtern vorkommt."""

    def __init__(self, path: Path = MOCK_PRODUCTS_FILE, failing_chains: tuple[str, ...] = (),
                 max_queries: int = config.MAX_GROCERY_QUERIES_PER_RUN) -> None:
        super().__init__(max_queries)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.price_date = date.fromisoformat(data["price_date"])
        self._entries: list[tuple[set[str], Product]] = []
        for e in data["products"]:
            p = Product(**{k: v for k, v in e.items() if k != "keywords"}, price_date=self.price_date)
            self._entries.append(({k.lower() for k in e["keywords"]}, p))
        self.failing_chains = failing_chains  # simuliert Ausfall einer Kette

    def _search(self, query: str, chains: tuple[Chain, ...], limit: int) -> SearchResult:
        words = [w for w in query.lower().replace(",", " ").split() if len(w) > 2]
        res = SearchResult(query=query)
        for chain in chains:
            if chain in self.failing_chains:
                res.errors[chain] = "Mock: Kette nicht erreichbar"
                continue
            hits = [p for kws, p in self._entries if p.chain == chain and any(_match(w, kw) for w in words for kw in kws)]
            res.products += hits[:limit]
            res.from_cache[chain] = False
        return res
