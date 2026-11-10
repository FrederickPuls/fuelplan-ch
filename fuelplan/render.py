"""Markdown-Ausgabe im Format aus CLAUDE.md.

Teil A: Tagesanalyse → drei Varianten, je mit echtem Preis pro Portion aus der Produktwahl (Schritt 10) neben
der Schätzung des Modells und der Einkaufssumme; Makros bleiben „(geschätzt)“.
Teil B: Einkaufsliste nur der gewählten Variante: Zutat | Laden | Produkt | Packungsgrösse | Anzahl |
Preis | Gesamt | Aktion, Gesamtsumme, Aktionen markiert, echter Preis/Portion und Abweichung zur Schätzung.
"""

from __future__ import annotations

from fuelplan import config
from fuelplan.compute import ShoppingList
from fuelplan.llm.schemas import PlanResponse, Recipe
from fuelplan.models import Activity, DayContext
from fuelplan.nutrition import rules as R

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
TYPE_LABELS = {
    "running": "Lauf",
    "strength_training": "Kraft",
    "cycling": "Rad",
    "hiking": "Wandern",
    "other": "Surf (other)",
    "unknown": "Unbekannt",
}
VARIANT_LABELS = {"budget": "Budget", "schnell": "Schnell", "aufwendig": "Aufwendig"}
CHAIN_LABELS = {"migros": "Migros", "denner": "Denner", "coop": "Coop"}


def _n(value: float | None, digits: int = 0, suffix: str = "") -> str:
    if value is None:
        return "–"
    text = f"{value:.{digits}f}".replace(".", ",")
    return f"{text}{suffix}"


def _kcal(n: int) -> str:
    return f"{n:,}".replace(",", "'")


def _chf(x: float) -> str:
    return f"{x:.2f}"


def _activity_row(a: Activity) -> str:
    time = a.time.strftime("%H:%M") if a.time else "–"
    dist = _n(a.distance_km, 2, " km") if a.distance_km else "–"
    return (
        f"| {time} | {TYPE_LABELS.get(a.type.value, a.type.value)} | {a.name or '–'} | {_n(a.duration_min)} min | {dist} | "
        f"{_n(a.avg_hr)} | {_n(a.kcal)} | {_n(a.training_load)} | {a.te_label or '–'} |"
    )


def render_warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    return "> **Hinweise**\n" + "\n".join(f"> - {w}" for w in warnings) + "\n\n"


# --- Teil 1: Tagesanalyse ------------------------------------------------------------------------

def render_day_analysis(ctx: DayContext) -> str:
    d = ctx.date
    source = "Garmin-CSV" if d <= config.CSV_LAST_DAY else "intervals.icu"
    lines = [f"## Tagesanalyse – {WEEKDAYS[d.weekday()]} {d.strftime('%d.%m.%Y')}", ""]
    lines.append(f"**Trainings heute** (Quelle: {source})")
    lines.append("")
    if ctx.activities:
        lines.append("| Zeit | Typ | Name | Dauer | Distanz | Ø-Puls | kcal | Last | TE |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        lines += [_activity_row(a) for a in ctx.activities]
    else:
        lines.append("Kein Training aufgezeichnet.")
    lines.append("")
    if ctx.week_load_avg_7d is not None:
        lines.append(f"Ø Trainingslast der Trainingstage in den letzten {config.WEEK_WINDOW_DAYS} Tagen: {_n(ctx.week_load_avg_7d)}")
    else:
        lines.append(f"Ø Trainingslast der letzten {config.WEEK_WINDOW_DAYS} Tage: zu wenige Trainingstage für einen Schnitt")
    lines.append("")
    if ctx.classification:
        c = ctx.classification
        lines.append(f"**Tag-Typ: {c.label}** – {c.reason}")
        lines.append("")
    if ctx.needs:
        n = ctx.needs
        lines.append(
            f"**Tagesbedarf:** {_kcal(n.kcal)} kcal ({_kcal(n.kcal_range[0])}–{_kcal(n.kcal_range[1])}) · "
            f"KH {n.carbs_g} g ({n.carbs_g_range[0]}–{n.carbs_g_range[1]}) · "
            f"Protein {n.protein_g} g ({n.protein_g_range[0]}–{n.protein_g_range[1]}) · Fett {n.fat_g} g"
        )
        lines.append("")
        lines.append("Grobe Verteilung: " + " · ".join(
            f"{meal} {_kcal(round(n.kcal * share))} kcal" for meal, share in R.MEAL_SPLIT.items()
        ))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- Teil 2: Drei Varianten ------------------------------------------------------------------------

def render_recipe(r: Recipe, sl: ShoppingList | None = None) -> str:
    m = r.estimated_macros_per_portion
    lines = [f"### {VARIANT_LABELS.get(r.variant, r.variant)}: {r.name}", "", r.description, ""]
    port = f"für {r.portions} Portionen" if r.portions > 1 else "für 1 Portion"
    lines.append(f"**Zutaten** ({port}):")
    for i in r.ingredients:
        lines.append(f"- {i.name}: {i.grams} g" + (" (Vorrat)" if i.base_ingredient else ""))
    lines.append("")
    lines.append(f"**Kochzeit:** {r.cooking_minutes} min · **Geräte:** {', '.join(r.equipment) or '–'}")
    lines.append("")
    lines.append("**Zubereitung:**")
    lines += [f"{k}. {s}" for k, s in enumerate(r.steps, 1)]
    lines.append("")
    lines.append(f"**Makros pro Portion (geschätzt):** {_kcal(m.kcal)} kcal · KH {m.carbs_g} g · Protein {m.protein_g} g · Fett {m.fat_g} g")
    if sl is None:
        lines.append(f"**Preis pro Portion (geschätzt):** ca. {_chf(r.estimated_price_chf_per_portion)} CHF")
    else:
        tag = "echt, teils geschätzt" if sl.has_estimates else "echt"
        port_b = f" ({sl.portions} Portionen)" if sl.portions > 1 else ""
        lines.append(f"**Preis pro Portion{port_b}: {_chf(sl.price_per_portion_chf)} CHF ({tag}) · Schätzung {_chf(r.estimated_price_chf_per_portion)} CHF** · "
                     f"Einkauf gesamt {_chf(sl.total_chf)} CHF (ganze Packungen)" + (f" · Aktionen: {sl.promotions}" if sl.promotions else ""))
    return "\n".join(lines) + "\n"


def render_plan(ctx: DayContext, plan: PlanResponse, warnings: list[str], dinner_target: dict[str, int],
                shopping: dict[str, ShoppingList] | None = None, source_note: str = "") -> str:
    out = ["# FuelPlan CH – Teil A", ""]
    out.append(render_warnings(warnings))
    out.append(render_day_analysis(ctx))
    out.append("")
    out.append("## Drei Varianten für das Abendessen")
    out.append("")
    out.append(f"Ziel Abendessen (ca. {dinner_target['share_pct']} % des Tages): {_kcal(dinner_target['kcal'])} kcal · "
               f"KH {dinner_target['carbs_g']} g · Protein {dinner_target['protein_g']} g · Fett {dinner_target['fat_g']} g")
    out.append("")
    shopping = shopping or {}
    for variant in ("budget", "schnell", "aufwendig"):
        out.append(render_recipe(plan.by_variant(variant), shopping.get(variant)))
    if shopping:
        out.append("Preis pro Portion aus echten Produkten und Preisen (Teil A wählt für alle drei Varianten); Makros sind "
                   "Schätzungen des Modells." + (f" {source_note}" if source_note else ""))
    else:
        out.append("Preise und Makros sind Schätzungen des Modells.")
    out.append("")
    out.append("Auswahl: `python -m fuelplan shop budget|schnell|aufwendig` (Einkaufsliste aus der Produktwahl von Teil A, ohne neue Abfragen und ohne Modellaufruf)")
    return "\n".join(out).rstrip() + "\n"


# --- Teil 3: Einkaufsliste ---------------------------------------------------------------------------

def render_shopping(sl: ShoppingList, warnings: list[str], source_note: str = "") -> str:
    out = [f"# FuelPlan CH – Teil B: Einkaufsliste „{sl.recipe_name}“ ({VARIANT_LABELS.get(sl.variant, sl.variant)})", ""]
    out.append(render_warnings(warnings))
    if source_note:
        out.append(source_note)
        out.append("")
    out.append("| Zutat | Laden | Produkt | Packungsgrösse | Anzahl | Preis CHF | Gesamt CHF | Aktion? |")
    out.append("|---|---|---|---|---|---|---|---|")
    for l in sl.lines:
        if l.product is None:
            out.append(f"| {l.ingredient} ({l.grams} g) | – | kein Produkt: {l.reason} | – | – | {_chf(l.proportional_chf)} (geschätzt) | – | – |")
            continue
        p = l.product
        est = " (geschätzt)" if l.estimated else ""
        promo = "**Aktion**" if l.promotion else "–"
        if l.promotion and p.regular_price_chf:
            promo += f" statt {_chf(p.regular_price_chf)}"
        if l.promotion and p.promotion_until:
            promo += f" bis {p.promotion_until.strftime('%d.%m.')}"
        name = p.name + (f" ({l.note})" if l.note else "")
        out.append(f"| {l.ingredient} ({l.grams} g) | {CHAIN_LABELS.get(p.chain, p.chain)} | {name} | {p.size_text} | {l.packs} | {_chf(l.price_each_chf)}{est} | {_chf(l.total_chf)}{est} | {promo} |")
    out.append("")
    est_flag = " (enthält geschätzte Preise)" if sl.has_estimates else ""
    out.append(f"**Gesamtsumme Einkauf (ganze Packungen): {_chf(sl.total_chf)} CHF**{est_flag}")
    out.append(f"Anteilige Kosten des Rezepts: {_chf(sl.proportional_total_chf)} CHF"
               + (f", davon geschätzt {_chf(sl.estimated_share_chf)} CHF" if sl.estimated_share_chf else ""))
    port = f" ({sl.portions} Portionen)" if sl.portions > 1 else ""
    out.append(f"**Preis pro Portion{port}: {_chf(sl.price_per_portion_chf)} CHF** · Schätzung aus Teil A: {_chf(sl.estimated_price_per_portion_chf)} CHF · Abweichung {sl.deviation_chf:+.2f} CHF")
    if sl.promotions:
        out.append(f"Aktionen: {sl.promotions}")
    m = sl.macros_per_portion
    tag = " (geschätzt, keine Nährwerte zu allen Produkten)" if sl.macros_estimated else " (aus Nährwerten der Produkte)"
    out.append(f"**Makros pro Portion{tag}:** {_kcal(m.kcal)} kcal · KH {m.carbs_g} g · Protein {m.protein_g} g · Fett {m.fat_g} g")
    out.append("")
    out.append("Produktwahl (Begründung des Modells):")
    for l in sl.lines:
        if l.reason:
            out.append(f"- {l.ingredient}: {l.reason}")
    return "\n".join(out).rstrip() + "\n"
