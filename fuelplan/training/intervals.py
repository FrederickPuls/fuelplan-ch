"""intervals.icu REST-Client – ausschliesslich GET.

Auth: HTTP Basic, Benutzer „API_KEY“, Passwort = Key aus .env (INTERVALS_API_KEY).
Es werden nur Aktivitäts-Zusammenfassungen gelesen (keine Streams, keine Details),
nie Workouts angelegt, geändert oder gelöscht.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from fuelplan import config
from fuelplan.models import Activity, ActivityType, Source
from fuelplan.training import TrainingDataError

# intervals.icu-Typen → unsere Typen (alles andere → UNKNOWN; "Other" = Surf, siehe CLAUDE.md)
INTERVALS_TYPES = {
    "Run": ActivityType.RUNNING,
    "TrailRun": ActivityType.RUNNING,
    "VirtualRun": ActivityType.RUNNING,
    "WeightTraining": ActivityType.STRENGTH,
    "Workout": ActivityType.STRENGTH,
    "Ride": ActivityType.CYCLING,
    "VirtualRide": ActivityType.CYCLING,
    "GravelRide": ActivityType.CYCLING,
    "MountainBikeRide": ActivityType.CYCLING,
    "Hike": ActivityType.HIKING,
    "Walk": ActivityType.HIKING,
    "Other": ActivityType.OTHER,
}

_ALLOWED_METHODS = {"GET"}


def map_activity(raw: dict) -> Activity:
    """Ein Aktivitäts-Objekt der API auf Activity abbilden (nur Zusammenfassungsfelder)."""
    start = raw.get("start_date_local") or raw.get("start_date")
    dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
    if dt is None:
        raise TrainingDataError(f"Aktivität ohne Startzeit: id={raw.get('id')}")
    seconds = raw.get("moving_time") or raw.get("elapsed_time") or 0
    return Activity(
        date=dt.date(),
        time=dt.time().replace(second=0, microsecond=0),
        type=INTERVALS_TYPES.get(raw.get("type") or "", ActivityType.UNKNOWN),
        name=raw.get("name") or "",
        duration_min=round(seconds / 60, 1),
        distance_km=round((raw.get("distance") or 0) / 1000, 2),
        avg_hr=raw.get("average_heartrate"),
        max_hr=raw.get("max_heartrate"),
        kcal=raw.get("calories"),
        training_load=raw.get("icu_training_load"),
        te_label=None,  # intervals.icu liefert kein Garmin-Training-Effect-Label
        source=Source.INTERVALS,
        external_id=str(raw["id"]) if raw.get("id") is not None else None,
    )


class IntervalsSource:
    """ActivitySource über die intervals.icu-API (nur GET)."""

    def __init__(self, api_key: str | None = None, athlete_id: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._api_key = api_key or config.require_env("INTERVALS_API_KEY")
        self.athlete_id = athlete_id or config.require_env("INTERVALS_ATHLETE_ID")
        self._client = httpx.Client(
            base_url=config.INTERVALS_BASE_URL,
            auth=("API_KEY", self._api_key),
            timeout=config.INTERVALS_TIMEOUT_S,
            headers={"Accept": "application/json", "User-Agent": "fuelplan-ch/0.1"},
            transport=transport,
        )

    def _get(self, path: str, params: dict) -> list[dict]:
        method = "GET"
        assert method in _ALLOWED_METHODS
        try:
            r = self._client.request(method, path, params=params)
        except httpx.TimeoutException as e:
            raise TrainingDataError(f"intervals.icu antwortet nicht (Timeout nach {config.INTERVALS_TIMEOUT_S:.0f} s).") from e
        except httpx.HTTPError as e:
            raise TrainingDataError(f"intervals.icu nicht erreichbar: {e.__class__.__name__}.") from e
        if r.status_code in (401, 403):
            raise TrainingDataError("intervals.icu lehnt den Zugriff ab (401/403): INTERVALS_API_KEY oder INTERVALS_ATHLETE_ID prüfen.")
        if r.status_code == 429:
            raise TrainingDataError("intervals.icu Rate-Limit erreicht (429), später erneut versuchen.")
        if r.status_code >= 400:
            raise TrainingDataError(f"intervals.icu Fehler {r.status_code} für {path}.")
        try:
            data = r.json()
        except ValueError as e:
            raise TrainingDataError("intervals.icu lieferte kein JSON.") from e
        return data or []

    def activities(self, oldest: date, newest: date) -> list[Activity]:
        raw = self._get(f"/athlete/{self.athlete_id}/activities",
                        {"oldest": oldest.isoformat(), "newest": newest.isoformat()})
        return [map_activity(a) for a in raw]

    def raw_keys(self, oldest: date, newest: date) -> list[str]:
        """Nur zur Diagnose: Feldnamen (keine Werte) der ersten Aktivität im Zeitraum."""
        raw = self._get(f"/athlete/{self.athlete_id}/activities",
                        {"oldest": oldest.isoformat(), "newest": newest.isoformat()})
        return sorted(raw[0].keys()) if raw else []
