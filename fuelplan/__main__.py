"""CLI: python -m fuelplan <befehl>

  day    [--date YYYY-MM-DD|heute]                       Tagesanalyse ohne LLM
  search <Begriff> ... [--mock]                            Produkte pro Laden (Bridge-Test)
  today  [--date] [--variant V] [--mock] [--dry-run]       Teil A: Tagesanalyse + 3 Varianten mit echten Preisen (+ Teil B mit --variant)
  shop   budget|schnell|aufwendig [--run ORDNER]           Teil B: Einkaufsliste aus der Produktwahl des letzten Laufs (keine Abfragen, kein LLM)
  usage  [--month YYYY-MM] [--offline]                     Monatskosten gegen Budget + Restguthaben (OpenRouter)
  serve  [--mock] [--dry-run] [--port 8000]                Phase 2: API für die PWA auf 127.0.0.1 (nur lokal)
  demo   [--port 8000] [--data-dir ORDNER]                 Demo ohne Keys: erfundene Trainingswoche, Mock-Preise, gespeicherte Antworten
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fuelplan import config
from fuelplan.nutrition.daytype import classify
from fuelplan.nutrition.needs import compute_needs
from fuelplan.render import render_day_analysis
from fuelplan.training import TrainingDataError
from fuelplan.training.garmin_csv import GarminCsvSource
from fuelplan.training.intervals import IntervalsSource
from fuelplan.training.merge import build_day_context


def cmd_day(args: argparse.Namespace) -> int:
    day = config.parse_date(args.date)
    csv_source = GarminCsvSource()
    needs_api = day > config.CSV_LAST_DAY  # auch das Wochenfenster reicht sonst nicht über den Stichtag hinaus
    try:
        api_source = IntervalsSource() if needs_api else None
        ctx = build_day_context(day, csv_source, api_source)
    except (TrainingDataError, RuntimeError) as e:
        print(f"Abbruch: {e}\nOhne Trainingsdaten gibt es keine Tagesanalyse.", file=sys.stderr)
        return 2
    ctx.classification = classify(ctx)
    ctx.needs = compute_needs(ctx.classification)
    if args.json:
        print(ctx.model_dump_json(indent=2, exclude_none=True))
    else:
        print(render_day_analysis(ctx))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from fuelplan.grocery.mock import MockBridge
    from fuelplan.grocery.price_cache import PriceCache, is_base_ingredient
    from fuelplan.grocery.swissgroceries import SwissGroceriesBridge, SwissGroceriesError

    try:
        bridge = MockBridge() if args.mock else SwissGroceriesBridge(use_store_ids=args.store_ids)
    except SwissGroceriesError as e:
        print(f"Abbruch: {e}", file=sys.stderr)
        return 2
    cache = PriceCache() if args.cache else None
    with bridge:
        for query in args.queries:
            products, errors, note = None, {}, ""
            if cache and is_base_ingredient(query):
                products = cache.get(query)
                if products:
                    note = f" (Basiszutat, aus Preis-Cache vom {products[0].price_date}, geschätzt)"
            if products is None:
                r = bridge.search(query, limit=args.limit)
                products, errors = r.products, r.errors
                if cache and is_base_ingredient(query):
                    cache.put(query, products)
            print(f"\n### {query}{note}")
            for chain in config.GROCERY_CHAINS:
                hits = [p for p in products if p.chain == chain]
                head = f"{chain}: {len(hits)} Treffer" + (f" – FEHLER: {errors[chain]}" if chain in errors else "")
                print(head)
                for p in hits:
                    promo = f"  AKTION statt {p.regular_price_chf:.2f}" if p.promotion and p.regular_price_chf else ("  AKTION" if p.promotion else "")
                    unit = f" ({p.unit_price_chf:.2f}/{p.unit_price_per})" if p.unit_price_chf else ""
                    est = " (geschätzt)" if p.estimated else ""
                    print(f"  - {p.name} | {p.size_text} | {p.price_chf:.2f} CHF{unit}{promo}{est} | id {p.product_id}")
        print(f"\nAbfragen: {bridge.queries_made} von max. {bridge.max_queries}")
    return 0


def _pipeline(args: argparse.Namespace):
    from fuelplan.pipeline import Pipeline
    return Pipeline(mock=args.mock, dry_run=args.dry_run)


def _choose_variant() -> str | None:
    if not sys.stdin.isatty():
        return None
    try:
        answer = input("Variante wählen [budget/schnell/aufwendig, leer = später]: ").strip().lower()
    except EOFError:
        return None
    return answer if answer in ("budget", "schnell", "aufwendig") else None


def cmd_today(args: argparse.Namespace) -> int:
    from fuelplan.grocery.swissgroceries import SwissGroceriesError
    from fuelplan.llm.client import LLMError
    from fuelplan.training import TrainingDataError

    day = config.parse_date(args.date)
    pipe = _pipeline(args)
    try:
        a = pipe.part_a(day)
    except (TrainingDataError, RuntimeError, SwissGroceriesError) as e:
        print(f"Abbruch: {e}", file=sys.stderr)
        return 2
    except LLMError as e:
        print(f"Abbruch beim Modellaufruf: {e}", file=sys.stderr)
        return 3
    print(a.output)
    print(f"[Lauf: {a.run.path}]", file=sys.stderr)
    variant = args.variant or _choose_variant()
    if not variant:
        return 0
    return _shop(pipe, variant, a.run)


def _shop(pipe, variant: str, run=None) -> int:
    try:
        b = pipe.part_b(variant, run)
    except RuntimeError as e:
        print(f"Abbruch: {e}", file=sys.stderr)
        return 2
    print(b.output)
    print(f"[Lauf: {b.run.path} · Rezept im Archiv]", file=sys.stderr)
    return 0


def cmd_shop(args: argparse.Namespace) -> int:
    from fuelplan.runlog import RunDir

    run = RunDir(args.run) if args.run else None
    return _shop(_pipeline(args), args.variant, run)


def cmd_usage(args: argparse.Namespace) -> int:
    from fuelplan.runlog import month_summary, render_month_summary

    if args.month:
        y, m = (int(x) for x in args.month.split("-"))
    else:
        t = config.today()
        y, m = t.year, t.month
    summary = month_summary(y, m)
    credits = None
    if not args.offline:
        try:
            from fuelplan.llm.openrouter import credits as fetch_credits
            credits = fetch_credits()
        except Exception as e:  # noqa: BLE001 – Übersicht soll auch ohne Netz gehen
            print(f"Hinweis: Restguthaben nicht abrufbar ({e.__class__.__name__}).", file=sys.stderr)
    print(render_month_summary(summary, credits))
    if summary["budget_left_usd"] < 0:
        print("WARNUNG: Monatsbudget überschritten.", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from fuelplan.api.app import create_app

    app = create_app(mock=args.mock, dry_run=args.dry_run)
    print(f"FuelPlan API: http://{config.API_HOST}:{args.port}  (mock={args.mock}, dry_run={args.dry_run}) – "
          f"nur lokal; Freigabe im Tailnet erst in Schritt 6 über `tailscale serve`.", file=sys.stderr)
    uvicorn.run(app, host=config.API_HOST, port=args.port, log_level="info")  # Host bewusst nicht konfigurierbar
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    import uvicorn

    from fuelplan.demo import create_demo_app

    app = create_demo_app(data_dir=args.data_dir)
    print(f"FuelPlan Demo: http://{config.API_HOST}:{args.port}  – erfundene Trainingswoche, Mock-Preise, gespeicherte "
          f"Modellantworten; kein Netz, keine Keys. Daten in {app.state.demo_data_dir}", file=sys.stderr)
    uvicorn.run(app, host=config.API_HOST, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fuelplan", description="FuelPlan CH – Phase 1")
    sub = parser.add_subparsers(dest="command", required=True)
    p_day = sub.add_parser("day", help="Tagesanalyse (Trainings, Tag-Typ, Bedarf) ohne LLM")
    p_day.add_argument("--date", default="heute", help="YYYY-MM-DD oder 'heute' (Europe/Zurich)")
    p_day.add_argument("--json", action="store_true", help="DayContext als JSON statt Markdown")
    p_day.set_defaults(func=cmd_day)
    p_s = sub.add_parser("search", help="Produkte für Suchbegriffe bei Migros/Denner/Coop (Bridge-Test)")
    p_s.add_argument("queries", nargs="+", help="Suchbegriffe, z. B. Pouletbrust 'Basmati Reis' Broccoli")
    p_s.add_argument("--mock", action="store_true", help="Mock-Bridge statt swissgroceries")
    p_s.add_argument("--limit", type=int, default=config.GROCERY_SEARCH_LIMIT)
    p_s.add_argument("--store-ids", action="store_true", help="Filialen aus stores.json mitgeben")
    p_s.add_argument("--cache", action="store_true", help="Preis-Cache für Basiszutaten verwenden")
    p_s.set_defaults(func=cmd_search)
    p_t = sub.add_parser("today", help="Teil A: Tagesanalyse + drei Varianten mit echten Preisen; mit --variant direkt Teil B")
    p_t.add_argument("--date", default="heute")
    p_t.add_argument("--variant", choices=["budget", "schnell", "aufwendig"])
    p_t.add_argument("--mock", action="store_true", help="Mock-Supermarkt-Bridge")
    p_t.add_argument("--dry-run", action="store_true", help="gespeicherte LLM-Antworten, kein Guthaben")
    p_t.set_defaults(func=cmd_today)
    p_b = sub.add_parser("shop", help="Teil B: Einkaufsliste der gewählten Variante aus der Produktwahl des letzten Laufs (keine Abfragen, kein LLM)")
    p_b.add_argument("variant", choices=["budget", "schnell", "aufwendig"])
    p_b.add_argument("--run", help="Run-Ordner statt des letzten")
    p_b.add_argument("--mock", action="store_true", help="ohne Wirkung in Teil B (Mock-Cache-Pfad), nur für Symmetrie zu today")
    p_b.add_argument("--dry-run", action="store_true", help="Archiv-Eintrag als dry_run markieren")
    p_b.set_defaults(func=cmd_shop)
    p_u = sub.add_parser("usage", help="Monatskosten aller Läufe gegen MONTHLY_BUDGET_USD, Restguthaben laut OpenRouter")
    p_u.add_argument("--month", help="YYYY-MM (Standard: aktueller Monat)")
    p_u.add_argument("--offline", action="store_true", help="kein Abruf des Restguthabens")
    p_u.set_defaults(func=cmd_usage)
    p_v = sub.add_parser("serve", help="Phase 2: API-Server für die PWA, bindet nur an 127.0.0.1 (kein --host)")
    p_v.add_argument("--mock", action="store_true", help="Mock-Supermarkt-Bridge")
    p_v.add_argument("--dry-run", action="store_true", help="gespeicherte LLM-Antworten, kein Guthaben, kein Restguthaben-Abruf")
    p_v.add_argument("--port", type=int, default=config.API_PORT)
    p_v.set_defaults(func=cmd_serve)
    p_d = sub.add_parser("demo", help="Demo ohne Keys und eigene Daten: erfundene Trainingswoche, Mock-Preise, gespeicherte Modellantworten")
    p_d.add_argument("--port", type=int, default=config.API_PORT)
    p_d.add_argument("--data-dir", type=Path, help="Ordner für Läufe, Archiv und Cache der Demo (Standard: temporärer Ordner)")
    p_d.set_defaults(func=cmd_demo)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
