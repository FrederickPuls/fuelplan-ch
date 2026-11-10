"""swissgroceries-mcp als MCP-Client (stdio über npx), nur das Tool search_products (und optional get_promotions).

Der Server läuft in einem Hintergrund-Thread mit eigener Event-Loop; Aufrufe aus dem
synchronen Code gehen über eine Queue. Ketten: nur config.GROCERY_CHAINS. Kein Scraping.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import Future
from datetime import date
from pathlib import Path

from fuelplan import config
from fuelplan.grocery.base import Chain, GroceryBridge, Nutrition100g, Product, SearchResult

_STOP = object()


# --- Abbildung ------------------------------------------------------------------------------

def _num(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _date(x) -> date | None:
    if not x or not isinstance(x, str):
        return None
    try:
        return date.fromisoformat(x[:10])
    except ValueError:
        return None


def map_product(raw: dict, price_date: date | None = None) -> Product | None:
    """Normalisiertes swissgroceries-Produkt → Product. None bei fehlendem/ungültigem Preis."""
    chain = raw.get("chain")
    if chain not in config.GROCERY_CHAINS:
        return None
    price = raw.get("price") or {}
    current = _num(price.get("current"))
    if not current or current <= 0:
        return None
    regular = _num(price.get("regular"))
    size = raw.get("size") or {}
    unit_price = raw.get("unitPrice") or {}
    promo = raw.get("promotion")
    promo_dict = promo if isinstance(promo, dict) else {}
    is_promo = bool(promo_dict) or (regular is not None and regular > current)
    promo_text = None
    if promo_dict:
        promo_text = (promo_dict.get("description") or promo_dict.get("text") or promo_dict.get("name")
                      or promo_dict.get("label") or promo_dict.get("discount"))
        if promo_text is not None and not isinstance(promo_text, str):
            promo_text = json.dumps(promo_text, ensure_ascii=False)
    # Denner (und ggf. andere) geben bei Aktionen auf Frischware den Preis "per 100 g" an, nicht pro Packung.
    note = None
    size_value, size_unit = _num(size.get("value")), size.get("unit")
    if promo_text and "per 100 g" in promo_text.lower() and size_value and (size_unit or "").lower() in ("g", "kg"):
        grams = size_value * (1000 if size_unit.lower() == "kg" else 1)
        if grams > 100:
            pack = round(current * grams / 100, 2)
            note = f"Preis {current:.2f} CHF per 100 g, Packung ca. {grams:g} g → {pack:.2f} CHF gerechnet"
            unit_price = {"value": round(current * 10, 2), "per": "kg"}
            current = pack
    nutrition = None
    nut = raw.get("nutrition") or raw.get("nutrients")
    if isinstance(nut, dict):
        nutrition = Nutrition100g(
            kcal=_num(nut.get("kcal") or nut.get("energyKcal")),
            carbs_g=_num(nut.get("carbs") or nut.get("carbohydrates")),
            protein_g=_num(nut.get("protein")),
            fat_g=_num(nut.get("fat")),
        )
    return Product(
        chain=chain,
        product_id=str(raw.get("id")),
        name=raw.get("name") or "",
        brand=raw.get("brand"),
        size_value=size_value,
        size_unit=size_unit,
        price_chf=current,
        regular_price_chf=regular if is_promo else None,
        unit_price_chf=_num(unit_price.get("value")),
        unit_price_per=unit_price.get("per"),
        promotion=is_promo,
        promotion_until=_date(promo_dict.get("endsAt") or promo_dict.get("validTo") or promo_dict.get("endDate") or promo_dict.get("until")),
        promotion_text=promo_text,
        nutrition=nutrition,  # swissgroceries liefert derzeit keine Nährwerte (Stand 06.11.2026) → bleibt None
        price_date=price_date or config.today(),
        note=note,
    )


def parse_search_result(query: str, data: dict, chains: tuple[Chain, ...]) -> SearchResult:
    res = SearchResult(query=query)
    by_chain = data.get("byChain") or {}
    for err in data.get("errors") or []:
        if isinstance(err, dict):
            res.errors[str(err.get("chain"))] = f"{err.get('code', 'error')}: {err.get('reason') or err.get('message') or ''}".strip(": ")
    for chain in chains:
        items = by_chain.get(chain)
        if items is None and chain not in res.errors:
            res.errors[chain] = "keine Antwort"
        for raw in items or []:
            p = map_product(raw)
            if p:
                res.products.append(p)
        src = (data.get("sources") or {}).get(chain) or {}
        res.from_cache[chain] = bool(src.get("fromCache"))
    return res


def load_store_ids(path: Path = config.STORES_FILE) -> dict[str, list[str]]:
    if not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {chain: [s["id"] for s in stores] for chain, stores in data.get("stores", {}).items()}


# --- Bridge ------------------------------------------------------------------------------------

class SwissGroceriesError(RuntimeError):
    pass


class SwissGroceriesBridge(GroceryBridge):
    def __init__(self, max_queries: int = config.MAX_GROCERY_QUERIES_PER_RUN,
                 use_store_ids: bool = config.USE_STORE_IDS, timeout_s: float = config.SWISSGROCERIES_TIMEOUT_S) -> None:
        super().__init__(max_queries)
        self.timeout_s = timeout_s
        self.store_ids = load_store_ids() if use_store_ids else {}
        self._queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread = threading.Thread(target=self._run_thread, name="swissgroceries-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout_s):
            raise SwissGroceriesError("swissgroceries-mcp startet nicht (Timeout).")
        if self._startup_error:
            raise SwissGroceriesError(f"swissgroceries-mcp startet nicht: {self._startup_error}")

    # -- Hintergrund-Thread mit MCP-Session
    def _run_thread(self) -> None:
        try:
            asyncio.run(self._runner())
        except BaseException as e:  # noqa: BLE001
            self._startup_error = e
            self._ready.set()

    async def _runner(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if not config.NPX.exists():
            raise SwissGroceriesError(f"npx nicht gefunden: {config.NPX}")
        params = StdioServerParameters(
            command=str(config.NPX), args=["-y", config.SWISSGROCERIES_PACKAGE],
            env={"PATH": f"{config.NPX.parent}:/usr/bin:/bin", "HOME": os.environ.get("HOME", "")},
        )
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                self._ready.set()
                while True:
                    item = await self._queue.get()
                    if item is _STOP:
                        break
                    tool, args, fut = item
                    try:
                        res = await session.call_tool(tool, args)
                        text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
                        if res.isError:
                            raise SwissGroceriesError(text[:300] or f"{tool} fehlgeschlagen")
                        fut.set_result(json.loads(text) if text else {})
                    except BaseException as e:  # noqa: BLE001
                        fut.set_exception(e)

    def _call(self, tool: str, args: dict) -> dict:
        if self._loop is None or self._queue is None:
            raise SwissGroceriesError("swissgroceries-mcp nicht gestartet.")
        fut: Future = Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (tool, args, fut))
        try:
            return fut.result(timeout=self.timeout_s)
        except TimeoutError as e:
            raise SwissGroceriesError(f"{tool} antwortet nicht (Timeout {self.timeout_s:.0f} s).") from e

    # -- Schnittstelle
    def _search(self, query: str, chains: tuple[Chain, ...], limit: int) -> SearchResult:
        args: dict = {"query": query, "chains": list(chains), "limit": limit}
        if self.store_ids:
            ids = [sid for c in chains for sid in self.store_ids.get(c, [])]
            if ids:
                args["storeIds"] = ids
        try:
            data = self._call("search_products", args)
        except SwissGroceriesError as e:
            # Gesamtausfall: jede Kette bekommt den Fehler, der Aufrufer nimmt Schätzpreise
            return SearchResult(query=query, errors={c: str(e) for c in chains})
        return parse_search_result(query, data, chains)

    def promotions(self, query: str, chains: tuple[Chain, ...] = config.GROCERY_CHAINS) -> list[dict]:
        """Aktionen mit Stichwort (zählt als Abfrage). Rohdaten, nur für Diagnose/spätere Nutzung."""
        if self.queries_made >= self.max_queries:
            raise SwissGroceriesError("Abfrage-Limit erreicht.")
        self.queries_made += 1
        args: dict = {"query": query, "chains": list(chains)}
        ids = [sid for c in chains for sid in self.store_ids.get(c, [])]
        if ids:
            args["storeIds"] = ids
        data = self._call("get_promotions", args)
        return data if isinstance(data, list) else data.get("promotions", [])

    def close(self) -> None:
        if self._loop and self._queue:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, _STOP)
        self._thread.join(timeout=10)
