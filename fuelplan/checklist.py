"""Abhak-Zustand der Einkaufsliste (Phase 2, Schritt 2), gespeichert als checklist.json im Run-Ordner.

Die Positionen sind die Zutaten der Einkaufsliste der gewählten Variante (Zutatname = Schlüssel). Abgleich-Regel
(Entscheidung 08.11.2026, Grundlage für den Offline-Abgleich in Schritt 5): jede Änderung trägt `changed_at`
(eingehende Positionen ohne Zeitstempel gelten als „jetzt“); beim Zusammenführen gewinnt der neuere Stand, bei
gleichem Zeitstempel oder fehlendem gespeichertem Zeitstempel gewinnt „abgehakt“.
Wechselt die gewählte Variante (erneutes `shop`), beginnt die Liste leer.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from fuelplan import config
from fuelplan.compute import ShoppingList
from fuelplan.runlog import RunDir

CHECKLIST_FILE = "checklist.json"


class ChecklistItem(BaseModel):
    ingredient: str
    checked: bool = False
    changed_at: datetime | None = None


class ChecklistState(BaseModel):
    variant: str
    items: dict[str, ChecklistItem] = Field(default_factory=dict)  # Zutat → Zustand


def load(run: RunDir, variant: str) -> ChecklistState:
    """Gespeicherter Zustand für diese Variante; andere Variante oder keine Datei → leer."""
    if run.has(CHECKLIST_FILE):
        state = ChecklistState.model_validate(run.read_json(CHECKLIST_FILE))
        if state.variant == variant:
            return state
    return ChecklistState(variant=variant)


def save(run: RunDir, state: ChecklistState) -> None:
    run.write_json(CHECKLIST_FILE, state.model_dump(mode="json"))


def reset(run: RunDir) -> None:
    if run.has(CHECKLIST_FILE):
        (run.path / CHECKLIST_FILE).unlink()


def resolve(current: ChecklistItem | None, incoming: ChecklistItem) -> ChecklistItem:
    """Konfliktregel: neuerer Zeitstempel gewinnt; gleich oder fehlend → „abgehakt“ gewinnt."""
    if current is None:
        return incoming
    if current.changed_at and incoming.changed_at and current.changed_at != incoming.changed_at:
        return incoming if incoming.changed_at > current.changed_at else current
    if current.checked == incoming.checked:
        return incoming if incoming.changed_at else current
    return incoming if incoming.checked else current


def merge(state: ChecklistState, incoming: list[ChecklistItem], now: datetime | None = None) -> ChecklistState:
    """Eingehende Positionen in den Zustand einarbeiten (Positionen ohne Zeitstempel bekommen `now`)."""
    now = now or datetime.now(config.TZ)
    for item in incoming:
        item = item.model_copy(update={"changed_at": item.changed_at or now})
        state.items[item.ingredient] = resolve(state.items.get(item.ingredient), item)
    return state


def items_for(shopping: ShoppingList, state: ChecklistState) -> list[ChecklistItem]:
    """Eine Position pro Zutat der Einkaufsliste, in Listenreihenfolge, mit gespeichertem Zustand."""
    return [state.items.get(line.ingredient) or ChecklistItem(ingredient=line.ingredient) for line in shopping.lines]
