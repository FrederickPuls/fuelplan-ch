"""Tag-Typ-Tabelle und Schwellenwerte als Daten – die EINZIGE Quelle für diese Zahlen.

CLAUDE.md verweist hierher und führt die Zahlen nicht mehr doppelt. Alle Werte sind
Näherungen und Startannahmen (keine Ernährungsberatung); sie werden anhand von
notes.md angepasst. Logik (Reihenfolge der Prüfungen, Kombinationen) steht in
daytype.py, die Bedarfsrechnung in needs.py.

Tabelle anzeigen:  .venv/bin/python -m fuelplan.nutrition.rules
"""

from __future__ import annotations

from dataclasses import dataclass

from fuelplan import config
from fuelplan.models import ActivityType, DayType

# --- Referenzwerte Person ----------------------------------------------------------
# Körpergewicht für alle g/kg-Rechnungen: eigener Wert in .env (FUELPLAN_WEIGHT_KG), sonst der Beispielwert.
DEFAULT_BODY_WEIGHT_KG = 70.0
BODY_WEIGHT_KG = float(config.env("FUELPLAN_WEIGHT_KG") or DEFAULT_BODY_WEIGHT_KG)
BMR_KCAL = 1_750  # Grundumsatz ca. (Mifflin-St Jeor)
BASE_DAILY_KCAL = 2_400  # Alltagsumsatz ohne Training ca.

# --- Fett ----------------------------------------------------------------------------
FAT_MIN_G_PER_KG = 0.8  # Fett = Rest der Kalorien, aber mindestens 0.8 g/kg (ca. 60 g)
KCAL_PER_G_CARBS = 4
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_FAT = 9

# --- Schwellen für die Klassifikation ---------------------------------------------
REST_DAY_MAX_MIN = 20  # kein Training oder < 20 min gesamt → Ruhetag
LOCKER_RUN_MAX_KM = 4.0  # Lauf < 4 km → Locker
EASY_RUN_MIN_KM = 4.0  # Lauf 4 bis unter 9 km → Easy Run
LONG_RUN_LIGHT_MIN_KM = 9.0  # Lauf 9 bis unter 14 km → Long Run light
LONG_RUN_MIN_KM = 14.0  # Lauf ab 14 km → Long Run
LOCKER_CYCLING_MAX_MIN = 60  # Rad < 60 min, niedrige Intensität → Locker

# Intervall-Lauf → immer Intensiv (Name hat Vorrang vor Distanz, Puls und TE-Label).
INTERVAL_NAME_KEYWORDS = ("intervall",)  # Vergleich in Kleinbuchstaben; trifft "Intervall" und "Intervalle"
INTERVAL_TE_LABELS = frozenset({"VO2MAX", "ANAEROBIC_CAPACITY"})
# Diese Labels reichen allein NICHT für Intervall (kommen bei normalen Läufen oft vor):
NON_INTERVAL_TE_LABELS = frozenset({"TEMPO", "LACTATE_THRESHOLD"})
# Intervall-Lauf ≥ LONG_RUN_MIN_KM: bleibt Intensiv, kcal und KH aber von Long Run.

# Wettkampf → mindestens Intensiv. Absichtlich ohne "marathon", damit "Marathon-Vorbereitung" nicht trifft;
# den Wettkampf auf der Uhr z. B. "Zürich Marathon Wettkampf" nennen.
RACE_NAME_KEYWORDS = ("wettkampf", "race", "rennen")

# "Hoher Ø-Puls" bzw. "hohe Trainingslast relativ zur Woche" → Intensiv.
# Vorschläge (Schritt 2), gelten nur für Läufe, die sonst Locker oder Easy Run wären;
# Long Run (light) behält seine höheren kcal/KH-Werte.
HIGH_AVG_HR_BPM = 165  # Ø-Puls eines Laufs ≥ 165 → Intensiv
HIGH_LOAD_FACTOR_VS_WEEK = 2.0  # Tageslast > 2.0 × Ø-Last der Trainingstage der 7 Vortage → Intensiv
HIGH_LOAD_MIN_TRAINING_DAYS = 2  # Wochenschnitt nur verwenden, wenn mindestens so viele Trainingstage vorliegen

# Surf (auf der Uhr: `other`, in intervals.icu `Other`, oft "Surfen" im Namen):
SURF_ACTIVITY_TYPES = frozenset({ActivityType.OTHER})
SURF_NAME_KEYWORDS = ("surf", "wake")
# Surfen wird immer gleich behandelt (Entscheidung 06.11.2026, Variante A): jede Surf-Session ist eine
# Locker-Komponente, auch unter der Ruhetag-Grenze. Mit anderen Einheiten gilt die normale Kombinationsregel
# (höherer KH- und Protein-Wert, Kalorien = Haupttyp + Mehrbedarf der Komponente gegenüber dem Ruhetag).
# Gemessene Surf-kcal werden nicht zusätzlich addiert. Kein fester Zuschlag mehr.
SURF_DAY_TYPE = DayType.LOCKER
SURF_PROTEIN_UPPER_END = True  # Protein an Surftagen am oberen Rand (Oberkörper und Rumpf)
# Wanderungen (`hiking`) stehen nicht in der Tabelle; Vorschlag: wie Locker behandeln.
HIKING_DAY_TYPE = DayType.LOCKER


# --- Verteilung auf Mahlzeiten (grobe Orientierung, Vorschlag) ---------------------------
# Profil: Frühstück nur Proteindrink, Mittag Mensa/Takeaway, Abendessen = Hauptmahlzeit, die wir planen.
MEAL_SPLIT: dict[str, float] = {"Frühstück": 0.15, "Mittag": 0.30, "Abendessen": 0.40, "Snacks": 0.15}

# --- Tag-Typ-Tabelle -----------------------------------------------------------------
@dataclass(frozen=True)
class DayTypeRule:
    day_type: DayType
    definition: str  # Definition aus intervals.icu-Daten (Text für Begründung und Tabelle)
    kcal: tuple[int, int]  # Kalorien ca. (von, bis)
    carbs_g_per_kg: tuple[float, float]
    protein_g_per_kg: tuple[float, float]
    hint: str

    def carbs_g(self, weight_kg: float = BODY_WEIGHT_KG) -> tuple[int, int]:
        return (round(self.carbs_g_per_kg[0] * weight_kg), round(self.carbs_g_per_kg[1] * weight_kg))

    def protein_g(self, weight_kg: float = BODY_WEIGHT_KG) -> tuple[int, int]:
        return (round(self.protein_g_per_kg[0] * weight_kg), round(self.protein_g_per_kg[1] * weight_kg))


RULES: dict[DayType, DayTypeRule] = {
    r.day_type: r
    for r in (
        DayTypeRule(
            DayType.RUHETAG,
            "kein Training oder < 20 min",
            (2_400, 2_500), (3.0, 4.0), (1.8, 2.0),
            "Gemüse und Protein hoch, KH moderat",
        ),
        DayTypeRule(
            DayType.LOCKER,
            "Rad < 60 min oder Lauf < 4 km, niedrige Intensität (Ø-Puls Zone 1–2); Surftage",
            (2_700, 2_900), (4.0, 5.0), (1.8, 2.0),
            "normaler Tag, KH leicht erhöht",
        ),
        DayTypeRule(
            DayType.INTENSIV,
            "Intervalle, Tempo, Wettkampf, hoher Ø-Puls oder hohe Trainingslast relativ zur Woche",
            (2_900, 3_200), (5.0, 6.0), (1.8, 2.0),
            "KH vor und nach dem Training, schnelle Erholung",
        ),
        DayTypeRule(
            DayType.EASY_RUN,
            "Lauf 4 bis unter 9 km, niedrige Intensität",
            (2_700, 2_900), (4.0, 5.0), (1.8, 2.0),
            "normaler Tag, KH leicht erhöht",
        ),
        DayTypeRule(
            DayType.LONG_RUN_LIGHT,
            "Lauf 9 bis unter 14 km",
            (2_900, 3_200), (5.0, 6.0), (1.8, 2.0),
            "KH + Protein nach dem Lauf, genug trinken",
        ),
        DayTypeRule(
            DayType.LONG_RUN,
            "Lauf ab 14 km",
            (3_200, 3_500), (6.0, 8.0), (1.8, 2.0),
            "Nach dem Lauf KH + Protein innerhalb 1–2 h, Salz und Flüssigkeit",
        ),
        DayTypeRule(
            DayType.KRAFT,
            "Krafttraining (Strength/Weight Training in intervals.icu)",
            (2_700, 2_900), (4.0, 5.0), (2.0, 2.2),
            "Proteinreiche Hauptmahlzeit, 30–40 g Protein pro Mahlzeit",
        ),
    )
}

# Kombinationen (Logik in daytype.py/needs.py): höherer KH- und Protein-Wert; Kalorien addieren heisst hier:
# kcal des Haupttyps plus für jede weitere Komponente deren Mehrbedarf gegenüber dem Ruhetag
# (z. B. Easy Run + Kraft = 2'700–2'900 + (2'700–2'900 − 2'400–2'500) = 3'000–3'300).
# Reihenfolge der Prüfungen: Intervall → Wettkampf → Lauf nach Distanz (Summe) → Kraft → Surf → Kombinationen → Ruhetag.
# Zielwerte (needs.py): Mitte des Bereichs; Protein an Surftagen am oberen Rand.


def _kcal(n: int) -> str:
    """1'750 statt 1,750 (Schweizer Schreibweise wie in CLAUDE.md)."""
    return f"{n:,}".replace(",", "'")


def _range(lo: float, hi: float) -> str:
    return f"{lo:.1f}–{hi:.1f}"


def rules_table_markdown(weight_kg: float = BODY_WEIGHT_KG) -> str:
    """Die Tabelle im Format von CLAUDE.md (Phase 0), erzeugt aus RULES."""
    lines = [
        f"Körpergewicht {weight_kg:g} kg · Grundumsatz ca. {_kcal(BMR_KCAL)} kcal · "
        f"Alltagsumsatz ohne Training ca. {_kcal(BASE_DAILY_KCAL)} kcal",
        "",
        "| Tag-Typ | Definition (aus intervals.icu) | Kalorien ca. | Kohlenhydrate | Protein | Hinweis |",
        "|---|---|---|---|---|---|",
    ]
    for r in RULES.values():
        c_lo, c_hi = r.carbs_g(weight_kg)
        p_lo, p_hi = r.protein_g(weight_kg)
        lines.append(
            f"| {r.day_type.value} | {r.definition} | {_kcal(r.kcal[0])}–{_kcal(r.kcal[1])} | "
            f"{_range(*r.carbs_g_per_kg)} g/kg ({c_lo}–{c_hi} g) | "
            f"{_range(*r.protein_g_per_kg)} g/kg ({p_lo}–{p_hi} g) | {r.hint} |"
        )
    lines += [
        "",
        f"Fett: Rest der Kalorien, mindestens {FAT_MIN_G_PER_KG:g} g/kg (ca. {round(FAT_MIN_G_PER_KG * weight_kg)} g). "
        f"Surf: immer eine {SURF_DAY_TYPE.value}-Komponente (Kombinationsregel), Protein am oberen Rand. "
        f"Ruhetag: < {REST_DAY_MAX_MIN} min. Lauf: < {LOCKER_RUN_MAX_KM:g} km Locker, "
        f"{EASY_RUN_MIN_KM:g} bis unter {LONG_RUN_LIGHT_MIN_KM:g} km Easy Run, "
        f"{LONG_RUN_LIGHT_MIN_KM:g} bis unter {LONG_RUN_MIN_KM:g} km Long Run light, ab {LONG_RUN_MIN_KM:g} km Long Run. "
        f"Intervall: Name enthält {' / '.join(INTERVAL_NAME_KEYWORDS)} oder TE-Label {' / '.join(sorted(INTERVAL_TE_LABELS))}.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(rules_table_markdown())
