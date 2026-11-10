// Offline-Speicher der Einkaufsliste (Schritt 5): Liste und Abhak-Zustand der gewählten Variante liegen auf dem Gerät.
// Ohne Verbindung wird weiter abgehakt; jede Änderung trägt `changed_at` und bleibt „ausstehend“, bis der Server sie
// per PATCH /checklist angenommen hat. Zusammenführen macht der Server (Konfliktregel Abweichung 1.7); die App
// übernimmt danach seinen Stand. Alle Zugriffe auf den Speicher in try/catch – ohne Speicher läuft die App trotzdem.

import type { ChecklistItem, ShoppingList, Variant } from "./types";

export const STORAGE_KEY = "fuelplan.shopping.v1";

/** Das Wenige, das wir von localStorage brauchen – austauschbar für Tests. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface ItemState {
  checked: boolean;
  changed_at: string; // ISO, vom Gerät
}

export interface SavedShopping {
  runId: string;
  variant: Variant;
  savedAt: string;
  shopping: ShoppingList;
  /** Anzeigestand pro Zutat (Server-Stand plus lokale Änderungen). */
  items: Record<string, ItemState>;
  /** Lokale Änderungen, die der Server noch nicht bestätigt hat. */
  pending: Record<string, ItemState>;
}

export function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function load(storage: StorageLike | null): SavedShopping | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isSaved(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function persist(storage: StorageLike | null, saved: SavedShopping | null): boolean {
  if (!storage) return false;
  try {
    if (saved) storage.setItem(STORAGE_KEY, JSON.stringify(saved));
    else storage.removeItem(STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

function isSaved(x: unknown): x is SavedShopping {
  if (!x || typeof x !== "object") return false;
  const s = x as Partial<SavedShopping>;
  return typeof s.runId === "string" && typeof s.variant === "string" && !!s.shopping && Array.isArray(s.shopping.lines) && !!s.items && !!s.pending;
}

/** Server-Stand (Liste + Checkliste) übernehmen. Ausstehende lokale Änderungen desselben Laufs bleiben erhalten und
 *  überlagern die Anzeige, bis sie gesendet sind; ein anderer Lauf oder eine andere Variante ersetzt alles. */
export function fromServer(previous: SavedShopping | null, runId: string, variant: Variant, shopping: ShoppingList, serverItems: ChecklistItem[], now: string): SavedShopping {
  const same = previous !== null && previous.runId === runId && previous.variant === variant;
  const pending = same ? { ...previous.pending } : {};
  const items: Record<string, ItemState> = {};
  for (const it of serverItems) items[it.ingredient] = { checked: it.checked, changed_at: it.changed_at ?? "" };
  for (const [ing, st] of Object.entries(pending)) items[ing] = st; // lokal neuer als gesendet
  return { runId, variant, savedAt: now, shopping, items, pending };
}

/** Abhaken/Enthaken auf dem Gerät: Anzeige und ausstehende Liste bekommen den neuen Zustand mit Zeitstempel. */
export function toggle(saved: SavedShopping, ingredient: string, checked: boolean, now: string): SavedShopping {
  const st: ItemState = { checked, changed_at: now };
  return { ...saved, items: { ...saved.items, [ingredient]: st }, pending: { ...saved.pending, [ingredient]: st } };
}

/** Ausstehende Änderungen als PATCH-Körper (mit changed_at, damit der Server nach Regel 1.7 zusammenführt). */
export function pendingItems(saved: SavedShopping): ChecklistItem[] {
  return Object.entries(saved.pending).map(([ingredient, st]) => ({ ingredient, checked: st.checked, changed_at: st.changed_at }));
}

/** Antwort des Servers auf ein PATCH einarbeiten: gesendete Änderungen gelten als erledigt, Änderungen, die während des
 *  Sendens dazukamen (neuerer Zeitstempel), bleiben ausstehend und überlagern die Anzeige weiter. */
export function acknowledge(saved: SavedShopping, sent: ChecklistItem[], serverItems: ChecklistItem[], now: string): SavedShopping {
  const pending: Record<string, ItemState> = {};
  for (const [ing, st] of Object.entries(saved.pending)) {
    const s = sent.find((x) => x.ingredient === ing);
    if (!s || s.changed_at !== st.changed_at) pending[ing] = st;
  }
  const items: Record<string, ItemState> = {};
  for (const it of serverItems) items[it.ingredient] = { checked: it.checked, changed_at: it.changed_at ?? "" };
  for (const [ing, st] of Object.entries(pending)) items[ing] = st;
  return { ...saved, savedAt: now, items, pending };
}

export function hasPending(saved: SavedShopping | null): boolean {
  return !!saved && Object.keys(saved.pending).length > 0;
}

export function checkedCount(saved: SavedShopping): number {
  return saved.shopping.lines.filter((l) => saved.items[l.ingredient]?.checked).length;
}
