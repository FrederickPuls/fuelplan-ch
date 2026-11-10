"""Trainingsdaten: Garmin-CSV (bis Stichtag), intervals.icu (ab Stichtag), Zusammenführung."""


class TrainingDataError(RuntimeError):
    """Trainingsdaten nicht verfügbar – der Lauf bricht kontrolliert ab (keine Tagesanalyse ohne Daten)."""
