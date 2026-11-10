"""Tag-Typ-Klassifikation. Reines Python, keine API.

Reihenfolge (aus ../Phase1_Plan.md, Schritt 2):
Intervall → Wettkampf → Lauf nach Distanz (Summe) → Kraft → Surf (immer Locker-Komponente)
→ Kombinationen (höherer KH- und Protein-Wert, Kalorien addieren) → Ruhetag (< 20 min).
Zusätzlich (Vorschlag): hoher Ø-Puls oder hohe Last relativ zur Woche hebt Locker/Easy Run auf Intensiv.
Alle Zahlen kommen aus rules.py.
"""

from __future__ import annotations

from fuelplan.models import Activity, ActivityType, DayClassification, DayContext, DayType
from fuelplan.nutrition import rules as R

# Rangfolge bei gleichem kcal-Bereich (höher = Haupttyp)
_PRIORITY = {
    DayType.LONG_RUN: 7,
    DayType.INTENSIV: 6,
    DayType.LONG_RUN_LIGHT: 5,
    DayType.EASY_RUN: 4,
    DayType.KRAFT: 3,
    DayType.LOCKER: 2,
    DayType.RUHETAG: 1,
}


def _name_has(a: Activity, keywords: tuple[str, ...]) -> bool:
    name = a.name.lower()
    return any(k in name for k in keywords)


def is_interval_run(a: Activity) -> bool:
    """Intervall-Lauf: Name enthält Schlüsselwort ODER TE-Label in der Intervall-Liste. Nur für Läufe."""
    if a.type is not ActivityType.RUNNING:
        return False
    return _name_has(a, R.INTERVAL_NAME_KEYWORDS) or (a.te_label or "").upper() in R.INTERVAL_TE_LABELS


def is_race(a: Activity) -> bool:
    return a.type is ActivityType.RUNNING and _name_has(a, R.RACE_NAME_KEYWORDS)


def is_surf(a: Activity) -> bool:
    return a.type in R.SURF_ACTIVITY_TYPES or _name_has(a, R.SURF_NAME_KEYWORDS)


def run_type_by_distance(km: float) -> DayType:
    if km < R.LOCKER_RUN_MAX_KM:
        return DayType.LOCKER
    if km < R.LONG_RUN_LIGHT_MIN_KM:
        return DayType.EASY_RUN
    if km < R.LONG_RUN_MIN_KM:
        return DayType.LONG_RUN_LIGHT
    return DayType.LONG_RUN


def _fmt_km(km: float) -> str:
    return f"{km:.1f}".replace(".", ",") + " km"


def _band(t: DayType) -> str:
    """Distanzband eines Lauftyps für die Begründung, z. B. "9 bis unter 14 km"."""
    if t is DayType.LOCKER:
        return f"unter {R.LOCKER_RUN_MAX_KM:g} km"
    if t is DayType.EASY_RUN:
        return f"{R.EASY_RUN_MIN_KM:g} bis unter {R.LONG_RUN_LIGHT_MIN_KM:g} km"
    if t is DayType.LONG_RUN_LIGHT:
        return f"{R.LONG_RUN_LIGHT_MIN_KM:g} bis unter {R.LONG_RUN_MIN_KM:g} km"
    return f"ab {R.LONG_RUN_MIN_KM:g} km"


def _high_load(day_load: float, week_avg: float | None) -> bool:
    if week_avg is None or week_avg <= 0:
        return False
    return day_load > R.HIGH_LOAD_FACTOR_VS_WEEK * week_avg


def classify(ctx: DayContext) -> DayClassification:
    """Liefert Tag-Typ, Komponenten und eine Begründung in einem Satz."""
    acts = ctx.activities
    runs = [a for a in acts if a.type is ActivityType.RUNNING]
    strength = [a for a in acts if a.type is ActivityType.STRENGTH]
    cycling = [a for a in acts if a.type is ActivityType.CYCLING]
    hikes = [a for a in acts if a.type is ActivityType.HIKING]
    surfs = [a for a in acts if is_surf(a)]
    total_min = sum(a.duration_min for a in acts)

    components: list[tuple[DayType, str]] = []
    macro_source: DayType | None = None

    # 1–3: Läufe
    if runs:
        run_km = sum(a.distance_km for a in runs)
        intervals = [a for a in runs if is_interval_run(a)]
        races = [a for a in runs if is_race(a)]
        if intervals:
            a = intervals[0]
            how = "Name" if _name_has(a, R.INTERVAL_NAME_KEYWORDS) else f"TE-Label {a.te_label}"
            text = f"„{a.name}“ ein Intervall-Lauf ist ({how})"
            if run_km >= R.LONG_RUN_MIN_KM:
                macro_source = DayType.LONG_RUN
                text += f", mit {_fmt_km(run_km)} gelten kcal und KH vom Long Run"
            components.append((DayType.INTENSIV, text))
        elif races:
            components.append((DayType.INTENSIV, f"„{races[0].name}“ ein Wettkampf ist"))
        else:
            t = run_type_by_distance(run_km)
            desc = f"der Lauf {_fmt_km(run_km)}" if len(runs) == 1 else f"2 Läufe zusammen {_fmt_km(run_km)}".replace("2 Läufe", f"{len(runs)} Läufe")
            text = f"{desc} lang {'ist' if len(runs) == 1 else 'sind'} ({_band(t)})"
            if t in (DayType.LOCKER, DayType.EASY_RUN):
                hrs = [a.avg_hr for a in runs if a.avg_hr]
                loads = [a.training_load or 0 for a in runs]
                if hrs and max(hrs) >= R.HIGH_AVG_HR_BPM:
                    t = DayType.INTENSIV
                    text = f"{desc} mit hohem Ø-Puls {max(hrs):.0f} intensiv war"
                elif _high_load(sum(loads), ctx.week_load_avg_7d):
                    t = DayType.INTENSIV
                    text = (
                        f"{desc} mit Trainingslast {sum(loads):.0f} über dem "
                        f"{R.HIGH_LOAD_FACTOR_VS_WEEK:g}-fachen Wochenschnitt ({ctx.week_load_avg_7d:.0f}) liegt"
                    )
            components.append((t, text))

    # Rad (nicht in den Daten, nur der Vollständigkeit halber)
    if cycling:
        mins = sum(a.duration_min for a in cycling)
        components.append((DayType.LOCKER, f"{mins:.0f} min Rad als Locker zählt"))

    # 4: Kraft
    if strength:
        mins = sum(a.duration_min for a in strength)
        components.append((DayType.KRAFT, f"{mins:.0f} min Krafttraining"))

    # Wandern (nicht in der Tabelle, Vorschlag: wie Locker)
    if hikes:
        mins = sum(a.duration_min for a in hikes)
        components.append((DayType.LOCKER, f"{mins:.0f} min Wandern wie Locker zählt"))

    # 7 (vorgezogen): Ruhetag bei sehr wenig Training – Surf hat Vorrang (gilt immer mindestens als Locker)
    if not surfs and total_min < R.REST_DAY_MAX_MIN:
        why = "kein Training" if not acts else f"nur {total_min:.0f} min Training (unter {R.REST_DAY_MAX_MIN} min)"
        return DayClassification(day_type=DayType.RUHETAG, components=[DayType.RUHETAG], reason=f"Ruhetag, weil {why}.")

    # 5: Surf – immer eine Locker-Komponente, auch unter der Ruhetag-Grenze
    if surfs:
        n = len(surfs)
        mins = sum(a.duration_min for a in surfs)
        verb = "zählen" if n > 1 else "zählt"
        components.append((R.SURF_DAY_TYPE, f"{n} Surf-Session{'s' if n > 1 else ''} ({mins:.0f} min) als {R.SURF_DAY_TYPE.value} {verb}"))

    # 6: Kombinationen – Haupttyp = höchster kcal-Bereich, dann Rangfolge
    components.sort(key=lambda c: (R.RULES[c[0]].kcal[1], R.RULES[c[0]].kcal[0], _PRIORITY[c[0]]), reverse=True)
    # gleiche Typen nur einmal (z. B. Surf + Wandern beide Locker), Begründungen zusammenführen
    merged: dict[DayType, str] = {}
    for t, text in components:
        merged[t] = f"{merged[t]} und {text}" if t in merged else text
    components = list(merged.items())

    types = [c for c, _ in components]
    result = DayClassification(day_type=types[0], components=types, reason="", macro_source=macro_source, surf=bool(surfs))
    parts = [text for _, text in components]
    reason = f"{result.label}, weil " + " und ".join(parts)
    if len(components) > 1:
        reason += " – Kombination: höherer KH- und Protein-Wert, Kalorien addiert"
    if surfs:
        reason += "; Protein am oberen Rand (Surftag)"
    result.reason = reason + "."
    return result
