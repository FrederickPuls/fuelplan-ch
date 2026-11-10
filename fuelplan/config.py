"""Konfiguration: .env laden, Pfade, Stichtag, Zeitzone, Modell-IDs, Limits.

Keys werden nur hier über python-dotenv geladen und nie ausgegeben oder geloggt.
"""

from __future__ import annotations

import os
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent  # fuelplan-ch/
load_dotenv(ROOT / ".env")


def env(name: str) -> str | None:
    """Umgebungsvariable lesen; leer = nicht gesetzt."""
    value = os.environ.get(name, "").strip()
    return value or None


def first_existing(*paths: Path) -> Path:
    """Erster vorhandener Pfad; gibt es keinen, der letzte (die Beispieldatei)."""
    for path in paths:
        if path.exists():
            return path
    return paths[-1]


def resolve_profile_file(root: Path = ROOT) -> Path:
    """Eigenes Profil `profile.md`; fehlt es, das Beispielprofil `profile.example.md`."""
    return first_existing(root / "profile.md", root / "profile.example.md")


# --- Zeit und Datenquellen ----------------------------------------------------------
TZ = ZoneInfo("Europe/Zurich")
CSV_LAST_DAY = date(2026, 11, 4)  # bis und mit: Garmin-CSV; ab dem Folgetag: intervals.icu
DATA_DIR = ROOT / "data"
ACTIVITIES_CSV = DATA_DIR / "garmin_activities_bis_2026-11-04.csv"
DAILY_CSV = DATA_DIR / "garmin_daily_bis_2026-11-04.csv"
WEEK_WINDOW_DAYS = 7  # Tage vor heute für den Wochenschnitt der Trainingslast

INTERVALS_BASE_URL = "https://intervals.icu/api/v1"
INTERVALS_TIMEOUT_S = 20.0

# --- Ausgabe / Läufe -------------------------------------------------------------------
RUNS_DIR = ROOT / "runs"
HISTORY_FILE = ROOT / "history" / "recipes.jsonl"
PROFILE_EXAMPLE_FILE = ROOT / "profile.example.md"  # fiktives Beispielprofil, Vorlage für das eigene profile.md
PROFILE_FILE = resolve_profile_file()  # profile.md, sonst profile.example.md

# --- Prompt-Längen (wie AgenTekki: Limit + Warnung) ------------------------------------
MAX_RECENT_RECIPES = 20  # Archiv-Einträge der letzten 14 Tage in der Plan-User-Message
RECENT_RECIPE_DAYS = 14
MAX_PRODUCTS_PER_CHAIN_AND_INGREDIENT = 5
MAX_USER_MESSAGE_CHARS = 12_000  # Plan-User-Message
MAX_EXECUTE_USER_MESSAGE_CHARS = 30_000  # Execute-User-Message: Produktlisten aller Suchbegriffe + drei Varianten
MAX_SYSTEM_PROMPT_CHARS = 12_000

# --- Supermärkte (swissgroceries-mcp) ----------------------------------------------------
GROCERY_CHAINS: tuple[str, ...] = ("migros", "denner", "coop")  # Coop nur über swissgroceries, nie scrapen
GROCERY_SEARCH_LIMIT = 5  # Treffer pro Kette und Abfrage
MAX_GROCERY_QUERIES_PER_RUN = 36  # Zutaten aller drei Varianten (Suchbegriffe nur einmal, Basiszutaten aus dem Cache)
PRICE_CACHE_FILE = ROOT / "cache" / "price_cache.json"
PRICE_CACHE_MAX_AGE_DAYS = 14
# Filialen um LOCATION_ZIP (einmalig mit find_stores): eigene stores.json, sonst die Beispieldatei mit Platzhaltern
STORES_FILE = first_existing(ROOT / "fuelplan" / "grocery" / "stores.json", ROOT / "fuelplan" / "grocery" / "stores.example.json")
USE_STORE_IDS = False  # storeIds bei search_products mitgeben (erst nach Test aktivieren)
# npx für swissgroceries-mcp: FUELPLAN_NPX aus .env (absoluter Pfad, z. B. bei nvm), sonst das npx im PATH
NPX = Path(env("FUELPLAN_NPX") or shutil.which("npx") or "npx")
SWISSGROCERIES_PACKAGE = "@nicktcode/swissgroceries-mcp"
SWISSGROCERIES_TIMEOUT_S = 45.0

# --- API (Phase 2) -----------------------------------------------------------------------
API_HOST = "127.0.0.1"  # nur lokal; Zugriff vom iPhone ausschliesslich über `tailscale serve` (Schritt 6), nie 0.0.0.0
API_PORT = 8000
WEB_DIST_DIR = ROOT / "web" / "dist"  # gebautes Frontend (ab Schritt 4); fehlt der Ordner, liefert "/" 404
SSE_KEEPALIVE_S = 15.0  # Kommentarzeile im SSE-Strom, wenn so lange kein Event kam

# --- Person / Ort / Budget ------------------------------------------------------------
LOCATION_ZIP = env("FUELPLAN_ZIP") or "8001"  # eigene PLZ in .env (FUELPLAN_ZIP); Standard: Zürich Zentrum
MONTHLY_BUDGET_USD = 10.0

# --- LLM ---------------------------------------------------------------------------------
LLM_PROVIDER = "openrouter"  # "openrouter" | "anthropic"
OPENROUTER_BASE_URL = "https://openrouter.ai/api"  # anthropic-SDK hängt /v1/messages an
OPENROUTER_PROVIDERS = ["anthropic"]  # Provider-Routing: nur Anthropic
OPENROUTER_APP_HEADERS = {"HTTP-Referer": "https://github.com/fuelplan-ch", "X-Title": "fuelplan-ch"}
# Modelle (Entscheidung 07.11.2026, Schritt 10): Haiku für beide Aufrufe. Sonnet bleibt als inaktive Konstante
# für einen schnellen Rückwechsel (nur die Zuweisung unten ändern).
MODEL_HAIKU = "anthropic/claude-haiku-5.5"  # 0.10 / 0.50 USD pro Mio. Tokens (OpenRouter-Modellliste 07.11.2026)
MODEL_SONNET = "anthropic/claude-sonnet-5.5"  # 2.00 / 10.00 USD pro Mio. Tokens – inaktiv
PLAN_MODEL = MODEL_HAIKU  # LLM-Aufruf 1 (Rezepte)
EXECUTE_MODEL = MODEL_HAIKU  # LLM-Aufruf 2 (Produktwahl für alle drei Varianten)
# Beide Modelle nehmen output_config.effort an (Haiku geprüft am 07.11.2026: effort "low" → 0 Denk-Tokens).
# Sonnet 5.5 denkt immer ("Reasoning is mandatory"); Denk-Tokens zählen gegen max_tokens und kosten Output-Preis.
PLAN_EFFORT = "medium"  # Rezepte: etwas Überlegung erwünscht
EXECUTE_EFFORT = "low"  # Produktwahl: deterministisch, kein Denken nötig
# max_tokens inkl. Denk-Tokens. Am 07.11. brach der Plan-Aufruf bei 4'000 ab (1'797 Denk-Tokens + JSON).
# Richtwerte Schritt 10: Plan 8'000, Execute (drei Varianten) 6'000. Gemessen im echten Lauf vom 07.11.2026 (Haiku):
# Plan 4'598 Output-Tokens (davon 2'305 Denk-Tokens bei effort medium), Execute 2'611 (24 Zutaten) → Limits belassen.
MAX_TOKENS_PLAN = 8000
MAX_TOKENS_EXECUTE = 6000
MAX_TOKENS_CAP = 16000  # Obergrenze für den frischen Wiederholungsversuch bei stop_reason == "max_tokens"
LLM_MAX_RETRIES = 2  # SDK-Retries bei 429/5xx
LLM_TIMEOUT_S = 120.0
# Preise USD pro Million Tokens (prompt, completion, cache_read, cache_write) – Fallback, falls die
# Antwort keine Kosten enthält (direkte Anthropic-API). Stand: OpenRouter-Modellliste 07.11.2026 (Haiku und Sonnet geprüft).
MODEL_PRICES_USD_PER_M = {
    "anthropic/claude-sonnet-5.5": (2.00, 10.00, 0.10, 2.50),
    "anthropic/claude-haiku-5.5": (0.10, 0.50, 0.01, 0.125),
}
MODEL_PRICES_DATE = "2026-11-07"


def require_env(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"{name} fehlt in .env (Vorlage: .env.example).")
    return value


def today() -> date:
    """„Heute“ in Europe/Zurich."""
    return datetime.now(TZ).date()


def parse_date(text: str | None) -> date:
    """'heute', 'today', leer → heute; sonst YYYY-MM-DD."""
    if not text or text.lower() in ("heute", "today"):
        return today()
    return date.fromisoformat(text)
