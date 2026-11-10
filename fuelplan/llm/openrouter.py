"""Kleine OpenRouter-Hilfsaufrufe ausserhalb des Modell-Clients: Key-Status und Guthaben (nur GET)."""

from __future__ import annotations

import httpx

from fuelplan import config

API = "https://openrouter.ai/api/v1"


def credits(timeout: float = 20.0) -> dict:
    """Key-Limit/-Verbrauch (/auth/key) und Gesamtguthaben (/credits). Der Key wird nie zurückgegeben."""
    key = config.require_env("OPENROUTER_API_KEY")
    headers = {"Authorization": f"Bearer {key}"}
    out: dict = {}
    with httpx.Client(timeout=timeout, headers=headers) as c:
        k = c.get(f"{API}/auth/key")
        k.raise_for_status()
        d = k.json().get("data", {})
        out.update(limit=float(d.get("limit") or 0.0), usage=float(d.get("usage") or 0.0),
                   limit_remaining=float(d.get("limit_remaining") or 0.0))
        cr = c.get(f"{API}/credits")
        cr.raise_for_status()
        d2 = cr.json().get("data", {})
        out.update(total_credits=float(d2.get("total_credits") or 0.0), total_usage=float(d2.get("total_usage") or 0.0))
    return out
