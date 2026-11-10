"""System-Prompts und Builder für die User-Messages der zwei LLM-Aufrufe.

PLAN_SYSTEM_PROMPT (statisch, cacheable): Rolle, Profil (profile.md), Budget, Geräte, Kochzeit, Ausgaberegeln.
Plan-User-Message: Tagesanalyse + Bedarf + Anteil Abendessen (Python) + Wochentag + Archiv der letzten 14 Tage.
EXECUTE_SYSTEM_PROMPT: nur aus gelieferten Produkten wählen, günstigstes passendes bzw. beste Aktion, "kein Produkt" erlaubt.
Execute-User-Message (Schritt 10, ein Aufruf für alle drei Varianten): jede Produktliste nur einmal (pro Suchbegriff,
Treffer pro Kette max. N), danach pro Variante die Zutaten mit Gramm und Verweis auf die Liste.
Längen sind begrenzt (config.MAX_*), Überschreitung gibt eine Warnung (warnings.warn), wie in AgenTekki.
"""

from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path

from fuelplan import config
from fuelplan.grocery.base import Product
from fuelplan.history import RecipeRecord
from fuelplan.llm.schemas import PlanResponse
from fuelplan.models import DayContext
from fuelplan.nutrition import rules as R
from fuelplan.render import TYPE_LABELS, WEEKDAYS

WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


class PromptTooLong(UserWarning):
    pass


def _check_len(text: str, limit: int, what: str) -> str:
    if len(text) > limit:
        warnings.warn(f"{what}: {len(text)} Zeichen, Limit {limit}", PromptTooLong, stacklevel=2)
    return text


def load_profile(path: Path = config.PROFILE_FILE) -> str:
    text = Path(path).read_text(encoding="utf-8")
    # Kopfzeile und Hinweis weglassen, ab "## Profil"
    idx = text.find("## Profil")
    return text[idx:].strip() if idx >= 0 else text.strip()


# --- Plan ------------------------------------------------------------------------------------------

PLAN_RULES = """## Deine Aufgabe
Du bist Koch- und Ernährungsassistent für genau eine Person (Profil unten). Du bekommst die Tagesanalyse
(Training, Tag-Typ, Tagesbedarf) und den Anteil, der auf das Abendessen entfällt. Schlag **genau drei
Abendessen** vor, je eines pro Variante:
- **budget**: so günstig wie möglich, Ziel unter 6 CHF pro Portion.
- **schnell**: in maximal 25 Minuten fertig, wenig Abwasch.
- **aufwendig**: darf länger dauern und das Budget leicht überschreiten (dann ausweisen), etwas Besonderes.

## Regeln
- Budget: Ziel 6–7 CHF pro Portion, maximal 10 CHF. Nur "aufwendig" darf leicht darüber liegen.
- Kochzeit unter der Woche 30–40 Minuten, am Wochenende auch länger. Nur die Geräte aus dem Profil.
- Makros des Abendessens sollen den Abendessen-Anteil des Tagesbedarfs ungefähr treffen (±15 %), vor allem
  Protein. Mengen in Gramm für die angegebene Portionenzahl; Stückware in Gramm (1 Ei ≈ 60 g).
- Zutaten, die es bei Migros, Denner oder Coop in der Schweiz gibt; Schweizer Bezeichnungen (Peperoni,
  Rüebli, Zucchetti, Poulet, Rahm). Pro Zutat ein kurzer Suchbegriff (1–3 Wörter), unter dem man das
  Produkt im Online-Shop findet, z. B. "Pouletbrust", "Basmati Reis", "Magerquark".
- Basiszutaten (Reis, Pasta, Haferflocken, Öl, Gewürze, Sojasauce, Bouillon …) als base_ingredient=true
  markieren; Salz, Pfeffer und Wasser nicht als Zutat aufführen.
- Vorkochen ist erlaubt (portions > 1), dann Mengen für alle Portionen und Preis/Makros pro Portion.
- Rezepte aus dem Archiv der letzten 14 Tage nicht wiederholen, auch nicht in leichter Abwandlung.
- Preis pro Portion und Makros pro Portion sind Schätzungen; sie werden später mit echten Produkten
  nachgerechnet. Keine Preise erfinden, die unrealistisch tief sind.
- Antworte ausschliesslich mit JSON nach dem vorgegebenen Schema, auf Deutsch, ohne Zusatztext.
"""


def build_plan_system_prompt(profile: str | None = None) -> str:
    profile = profile if profile is not None else load_profile()
    text = f"{PLAN_RULES}\n## Profil der Person\n{profile}\n"
    return _check_len(text, config.MAX_SYSTEM_PROMPT_CHARS, "PLAN_SYSTEM_PROMPT")


def dinner_share(ctx: DayContext) -> dict[str, int]:
    """Anteil Abendessen am Tagesbedarf (Python rechnet, nicht das Modell)."""
    assert ctx.needs is not None
    share = R.MEAL_SPLIT["Abendessen"]
    n = ctx.needs
    return {"kcal": round(n.kcal * share), "carbs_g": round(n.carbs_g * share),
            "protein_g": round(n.protein_g * share), "fat_g": round(n.fat_g * share), "share_pct": round(share * 100)}


def _activities_text(ctx: DayContext) -> str:
    if not ctx.activities:
        return "- kein Training"
    lines = []
    for a in ctx.activities:
        parts = [TYPE_LABELS.get(a.type.value, a.type.value), a.name or "", f"{a.duration_min:.0f} min"]
        if a.distance_km:
            parts.append(f"{a.distance_km:.1f} km")
        if a.avg_hr:
            parts.append(f"Ø-Puls {a.avg_hr:.0f}")
        if a.kcal:
            parts.append(f"{a.kcal:.0f} kcal")
        lines.append("- " + ", ".join(p for p in parts if p))
    return "\n".join(lines)


def build_plan_user_message(ctx: DayContext, recent: list[RecipeRecord], today: date | None = None) -> str:
    assert ctx.classification is not None and ctx.needs is not None
    d = ctx.date
    n = ctx.needs
    dinner = dinner_share(ctx)
    weekend = d.weekday() >= 5
    recent = recent[: config.MAX_RECENT_RECIPES]
    if recent:
        recent_text = "\n".join(
            f"- {r.date.strftime('%d.%m.')} ({r.variant}): {r.name} – {', '.join(r.main_ingredients)}" for r in recent
        )
    else:
        recent_text = "- (noch keine Einträge)"
    text = f"""## Tagesanalyse – {WEEKDAYS_LONG[d.weekday()]}, {d.strftime('%d.%m.%Y')} ({'Wochenende' if weekend else 'Werktag'})
Trainings heute:
{_activities_text(ctx)}

Tag-Typ: {ctx.classification.label} – {ctx.classification.reason}

Tagesbedarf gesamt: {n.kcal} kcal, Kohlenhydrate {n.carbs_g} g, Protein {n.protein_g} g, Fett {n.fat_g} g

## Zielwerte für das Abendessen (ca. {dinner['share_pct']} % des Tages)
{dinner['kcal']} kcal, Kohlenhydrate {dinner['carbs_g']} g, Protein {dinner['protein_g']} g, Fett {dinner['fat_g']} g

## Rezepte der letzten {config.RECENT_RECIPE_DAYS} Tage (nicht wiederholen)
{recent_text}

## Aufgabe
Drei Abendessen (budget, schnell, aufwendig) als JSON nach Schema. Kochzeit heute: {'auch länger möglich' if weekend else 'ca. 30–40 Minuten, "schnell" maximal 25'}.
"""
    return _check_len(text, config.MAX_USER_MESSAGE_CHARS, "Plan-User-Message")


# --- Execute -------------------------------------------------------------------------------------------

EXECUTE_SYSTEM_PROMPT = """Du wählst für drei Rezeptvarianten (budget, schnell, aufwendig) für jede Zutat das passende
Produkt aus Trefferlisten von Schweizer Supermärkten (Migros, Denner, Coop) aus.

Aufbau der Nachricht: zuerst die Produktlisten, eine je Suchbegriff (jede Liste steht nur einmal); danach pro
Variante die Zutaten mit benötigter Menge und dem Verweis auf ihre Liste.

Regeln:
- Wähle **ausschliesslich** Produkte aus der Liste, die bei der Zutat angegeben ist, über ihre Produkt-ID.
  Erfinde keine Produkte, IDs, Preise oder Läden.
- Pro Variante und Zutat genau eine Wahl: das günstigste **passende** Produkt (richtige Zutat, sinnvolle
  Qualität), oder die beste Aktion, wenn sie günstiger ist. Vergleiche über den Grundpreis (pro kg/l), nicht
  nur den Packungspreis. Dieselbe Zutat in zwei Varianten darf dasselbe Produkt bekommen.
- Packungsgrösse sinnvoll: so wenige Packungen wie nötig, um die benötigte Menge der jeweiligen Variante zu
  decken; bei Frischware lieber eine passende kleine Packung als eine grosse, die verdirbt. Bei Preisen
  "per 100 g" (Frischtheke) ist 1 Packung = die angegebene Menge.
- Passt kein Treffer zur Zutat (falsches Produkt, nur Fertiggerichte, nur unpassende Mengen), dann
  chain, product_id und packs auf null setzen und das kurz begründen. Das ist erlaubt und besser als
  ein falsches Produkt. Kein Ersatz durch eine andere Zutat (z. B. Zwiebeln statt Frühlingszwiebeln,
  Distelöl statt Sesamöl): dann ebenfalls null.
- Zutaten, die als "aus Vorrat/Cache" markiert sind, trotzdem zuordnen (Preis dient der Berechnung).
- Antworte ausschliesslich mit JSON nach Schema: `variant` und Zutatname exakt übernehmen. Schreibe pro Zutat
  zuerst die Begründung (ein kurzer Satz, der das gewählte Produkt beim Namen nennt), danach chain, product_id
  und packs genau dieses Produkts. ID und Begründung müssen zum selben Produkt gehören.
"""


def _product_line(p: Product) -> str:
    unit = f", {p.unit_price_chf:.2f} CHF/{p.unit_price_per}" if p.unit_price_chf and p.unit_price_per else ""
    promo = ""
    if p.promotion:
        promo = " AKTION" + (f" statt {p.regular_price_chf:.2f}" if p.regular_price_chf else "") + (f" bis {p.promotion_until.strftime('%d.%m.')}" if p.promotion_until else "")
    note = f" [{p.note}]" if p.note else ""
    est = " (Cache-Preis)" if p.estimated else ""
    return f"  - id={p.product_id} | {p.name} | {p.size_text} | {p.price_chf:.2f} CHF{unit}{promo}{est}{note}"


def build_execute_user_message(plan: PlanResponse, products: dict[str, list[Product]],
                               ingredient_query: dict[str, dict[str, str]],
                               errors: dict[str, dict[str, str]] | None = None) -> str:
    """products: Suchbegriff → Trefferliste (alle Ketten), jede Liste nur einmal;
    ingredient_query: Variante → Zutatname → Suchbegriff; errors: Suchbegriff → {Kette: Grund}."""
    errors = errors or {}
    index = {key: n for n, key in enumerate(products, 1)}
    blocks = ["## Produktlisten (eine je Suchbegriff, Treffer pro Kette)", ""]
    for key, hits in products.items():
        est = any(p.estimated for p in hits)
        blocks.append(f"### Liste {index[key]}: „{key}“" + (" (Basiszutat, aus Vorrat/Cache)" if est else ""))
        any_hit = False
        for chain in config.GROCERY_CHAINS:
            chain_hits = [p for p in hits if p.chain == chain][: config.MAX_PRODUCTS_PER_CHAIN_AND_INGREDIENT]
            err = errors.get(key, {}).get(chain)
            if chain_hits:
                any_hit = True
                blocks.append(f"- {chain}:")
                blocks += [_product_line(p) for p in chain_hits]
            elif err:
                blocks.append(f"- {chain}: nicht verfügbar ({err})")
            else:
                blocks.append(f"- {chain}: keine Treffer")
        if not any_hit:
            blocks.append("- → kein Produkt wählbar, null setzen")
        blocks.append("")
    blocks += ["## Varianten und Zutaten", ""]
    for recipe in plan.recipes:
        blocks.append(f"### Variante {recipe.variant}: {recipe.name} ({recipe.portions} Portion(en))")
        for ing in recipe.ingredients:
            key = ingredient_query.get(recipe.variant, {}).get(ing.name)
            ref = f"Liste {index[key]}" if key in index else "keine Liste, null setzen"
            base = " (Basiszutat)" if ing.base_ingredient else ""
            blocks.append(f"- {ing.name} – benötigt {ing.grams} g – {ref}{base}")
        blocks.append("")
    blocks.append("## Aufgabe\nFür jede Zutat jeder Variante genau eine Wahl (oder null) als JSON nach Schema. "
                  "`variant` und Zutatnamen exakt übernehmen; die Produkt-ID muss aus der bei der Zutat angegebenen Liste stammen.")
    return _check_len("\n".join(blocks), config.MAX_EXECUTE_USER_MESSAGE_CHARS, "Execute-User-Message")
