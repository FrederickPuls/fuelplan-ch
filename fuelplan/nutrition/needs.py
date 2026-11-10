"""Tagesbedarf (kcal, KH, Protein, Fett) aus der Klassifikation und dem Körpergewicht.

Reines Python; alle Zahlen aus rules.py. Zielwerte = Mitte des Bereichs,
Protein an Surftagen am oberen Rand, Fett = Rest, mindestens FAT_MIN_G_PER_KG.
Surfen ist eine normale Locker-Komponente (Kombinationsregel), kein Zuschlag.
"""

from __future__ import annotations

from fuelplan.models import DayClassification, DayType, Needs
from fuelplan.nutrition import rules as R


def _mid(lo: float, hi: float) -> float:
    return (lo + hi) / 2


def compute_needs(c: DayClassification, weight_kg: float = R.BODY_WEIGHT_KG) -> Needs:
    rules = [R.RULES[t] for t in c.components]
    primary = R.RULES[c.macro_source or c.day_type]
    rest = R.RULES[DayType.RUHETAG]

    # kcal: Haupttyp + Mehrbedarf jeder weiteren Komponente gegenüber dem Ruhetag
    kcal_lo, kcal_hi = primary.kcal
    for r in rules[1:]:
        kcal_lo += r.kcal[0] - rest.kcal[0]
        kcal_hi += r.kcal[1] - rest.kcal[1]

    # KH: höchster Bereich (Haupttyp bzw. macro_source und weitere Komponenten)
    carb_candidates = [primary.carbs_g(weight_kg)] + [r.carbs_g(weight_kg) for r in rules[1:]]
    carbs_lo, carbs_hi = max(carb_candidates, key=lambda x: (x[1], x[0]))
    # Protein: höchster Bereich aller Komponenten (macro_source ändert Protein nicht)
    protein_lo, protein_hi = max((r.protein_g(weight_kg) for r in rules), key=lambda x: (x[1], x[0]))

    kcal = round(_mid(kcal_lo, kcal_hi))
    carbs = round(_mid(carbs_lo, carbs_hi))
    protein = protein_hi if (c.surf and R.SURF_PROTEIN_UPPER_END) else round(_mid(protein_lo, protein_hi))

    fat_min = round(R.FAT_MIN_G_PER_KG * weight_kg)
    fat = round((kcal - carbs * R.KCAL_PER_G_CARBS - protein * R.KCAL_PER_G_PROTEIN) / R.KCAL_PER_G_FAT)
    if fat < fat_min:
        fat = fat_min
        kcal = carbs * R.KCAL_PER_G_CARBS + protein * R.KCAL_PER_G_PROTEIN + fat * R.KCAL_PER_G_FAT

    return Needs(
        kcal=kcal,
        carbs_g=carbs,
        protein_g=protein,
        fat_g=fat,
        kcal_range=(kcal_lo, kcal_hi),
        carbs_g_range=(carbs_lo, carbs_hi),
        protein_g_range=(protein_lo, protein_hi),
    )
