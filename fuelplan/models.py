"""Datenklassen für FuelPlan CH.

Enthält nur Struktur, keine Regeln. Die Zahlen der Tag-Typ-Tabelle stehen
ausschliesslich in `fuelplan/nutrition/rules.py`.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import time as Time
from enum import Enum

from pydantic import BaseModel, Field


class ActivityType(str, Enum):
    """Vereinheitlichte Aktivitätstypen (Garmin-CSV und intervals.icu werden darauf abgebildet)."""

    RUNNING = "running"
    STRENGTH = "strength_training"
    CYCLING = "cycling"
    HIKING = "hiking"
    OTHER = "other"  # auf der Uhr: Wakesurfen / Wakeboarden
    UNKNOWN = "unknown"


class Source(str, Enum):
    """Woher eine Aktivität stammt (Stichtag-Logik in training/merge.py)."""

    GARMIN_CSV = "garmin_csv"  # bis und mit 04.11.2026
    INTERVALS = "intervals"  # ab 05.11.2026


class DayType(str, Enum):
    """Tag-Typen aus der Tabelle in rules.py. Werte = Anzeigename in der Ausgabe."""

    RUHETAG = "Ruhetag"
    LOCKER = "Locker"
    INTENSIV = "Intensiv"
    EASY_RUN = "Easy Run"
    LONG_RUN_LIGHT = "Long Run light"
    LONG_RUN = "Long Run"
    KRAFT = "Kraft"


class Activity(BaseModel):
    """Eine Trainingseinheit, wie sie ans Modell geht (Tageszusammenfassung, keine Streams)."""

    date: Date
    time: Time | None = None
    type: ActivityType
    name: str = ""
    duration_min: float = Field(ge=0)
    distance_km: float = Field(default=0.0, ge=0)
    avg_hr: float | None = None
    max_hr: float | None = None
    kcal: float | None = None
    training_load: float | None = None
    aerobic_te: float | None = None
    anaerobic_te: float | None = None
    te_label: str | None = None  # z. B. AEROBIC_BASE, TEMPO, VO2MAX, ANAEROBIC_CAPACITY
    source: Source
    external_id: str | None = None  # ID bei intervals.icu, für Duplikat-Erkennung


class DailySummary(BaseModel):
    """Eine Zeile aus garmin_daily_*.csv bzw. das Pendant aus intervals.icu (optional)."""

    date: Date
    total_kcal: float | None = None
    active_kcal: float | None = None
    bmr_kcal: float | None = None
    steps: int | None = None
    resting_hr: int | None = None
    avg_stress: int | None = None


class Needs(BaseModel):
    """Tagesbedarf. Zielwerte sind die gewählten Punkte, die Bereiche kommen aus rules.py."""

    kcal: int
    carbs_g: int
    protein_g: int
    fat_g: int
    kcal_range: tuple[int, int]
    carbs_g_range: tuple[int, int]
    protein_g_range: tuple[int, int]


class DayClassification(BaseModel):
    """Ergebnis von nutrition/daytype.py: Tag-Typ mit Begründung in einem Satz."""

    day_type: DayType  # Haupttyp (höchster kcal-Bereich der Komponenten)
    components: list[DayType]  # alle beteiligten Typen, Haupttyp zuerst (Kombinationen: mehrere)
    reason: str  # ein Satz, z. B. "Intensiv, weil „Zürich - Intervalle 4 x 2 km“ ein Intervall-Lauf ist (Name)."
    macro_source: DayType | None = None  # Intervall-Lauf ab Long-Run-Distanz: kcal und KH von hier
    surf: bool = False  # mindestens eine Surf-Session heute (Locker-Komponente, Protein am oberen Rand)

    @property
    def label(self) -> str:
        """z. B. "Kraft + Locker (Surf)" – die Locker-Komponente eines Surftags wird als Surf ausgewiesen."""
        return " + ".join(
            f"{c.value} (Surf)" if self.surf and c is DayType.LOCKER else c.value for c in self.components
        )


class DayContext(BaseModel):
    """Alles, was Python über den Tag weiss, bevor das Modell befragt wird."""

    date: Date
    activities: list[Activity] = Field(default_factory=list)
    daily: DailySummary | None = None
    # Ø Trainingslast der Trainingstage in den 7 Tagen vor heute (für "Intensiv relativ zur Woche"),
    # None, wenn unbekannt oder zu wenige Trainingstage (siehe rules.HIGH_LOAD_MIN_TRAINING_DAYS)
    week_load_avg_7d: float | None = None
    classification: DayClassification | None = None
    needs: Needs | None = None

    @property
    def day_type(self) -> DayType | None:
        return self.classification.day_type if self.classification else None

    @property
    def total_training_min(self) -> float:
        return sum(a.duration_min for a in self.activities)

    @property
    def run_distance_km(self) -> float:
        return sum(a.distance_km for a in self.activities if a.type is ActivityType.RUNNING)
