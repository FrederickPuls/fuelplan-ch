// Offline-Speicher und Abgleich: speichern/laden, kaputter Speicher, abhaken ohne Netz, nachreichen, Server-Stand übernehmen.
import { describe, expect, it } from "vitest";
import { acknowledge, checkedCount, fromServer, hasPending, load, pendingItems, persist, STORAGE_KEY, toggle, type StorageLike } from "./offline";
import type { ChecklistItem, ShoppingList } from "./types";

class MemoryStorage implements StorageLike {
  map = new Map<string, string>();
  getItem(k: string) {
    return this.map.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.map.set(k, v);
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
}

class BrokenStorage implements StorageLike {
  getItem(): string | null {
    throw new Error("QuotaExceeded");
  }
  setItem(): void {
    throw new Error("QuotaExceeded");
  }
  removeItem(): void {
    throw new Error("QuotaExceeded");
  }
}

const shopping = {
  variant: "schnell",
  recipe_name: "Rindshack-Reispfanne",
  portions: 1,
  lines: [
    { ingredient: "Rindshackfleisch", grams: 150, product: null, packs: 1, price_each_chf: 9.75, total_chf: 9.75, proportional_chf: 2.9, estimated: false, promotion: false, reason: "" },
    { ingredient: "Mais", grams: 80, product: null, packs: 0, price_each_chf: 0.68, total_chf: 0, proportional_chf: 0.68, estimated: true, promotion: false, reason: "" },
    { ingredient: "Zwiebel", grams: 60, product: null, packs: 1, price_each_chf: 0.8, total_chf: 0.8, proportional_chf: 0.2, estimated: true, promotion: false, reason: "" },
  ],
  total_chf: 10.55,
  proportional_total_chf: 3.78,
  price_per_portion_chf: 3.78,
  estimated_price_per_portion_chf: 5.9,
  estimated_share_chf: 0.88,
  has_estimates: true,
  macros_per_portion: { kcal: 1100, carbs_g: 132, protein_g: 62, fat_g: 28 },
  macros_estimated: true,
  promotions: 0,
  warnings: [],
  store_totals: {},
  store_has_estimates: {},
} as unknown as ShoppingList;

const serverItems: ChecklistItem[] = [
  { ingredient: "Rindshackfleisch", checked: false, changed_at: null },
  { ingredient: "Mais", checked: true, changed_at: "2026-11-08T10:00:00+01:00" },
  { ingredient: "Zwiebel", checked: false, changed_at: null },
];

const T0 = "2026-11-08T11:00:00.000Z";
const T1 = "2026-11-08T11:05:00.000Z";
const T2 = "2026-11-08T11:06:00.000Z";

describe("speichern und laden", () => {
  it("legt die Liste mit Abhak-Zustand ab und liest sie wieder", () => {
    const st = new MemoryStorage();
    const saved = fromServer(null, "2026-11-08_1439", "schnell", shopping, serverItems, T0);
    expect(persist(st, saved)).toBe(true);
    const back = load(st);
    expect(back?.runId).toBe("2026-11-08_1439");
    expect(back?.items["Mais"]?.checked).toBe(true);
    expect(checkedCount(back!)).toBe(1);
  });

  it("liefert null bei leerem, kaputtem oder fremdem Inhalt", () => {
    const st = new MemoryStorage();
    expect(load(st)).toBeNull();
    st.setItem(STORAGE_KEY, "{nicht json");
    expect(load(st)).toBeNull();
    st.setItem(STORAGE_KEY, JSON.stringify({ foo: 1 }));
    expect(load(st)).toBeNull();
  });

  it("stürzt ohne Speicher oder mit werfendem Speicher nicht ab", () => {
    expect(load(null)).toBeNull();
    expect(persist(null, null)).toBe(false);
    const broken = new BrokenStorage();
    expect(load(broken)).toBeNull();
    expect(persist(broken, fromServer(null, "r", "budget", shopping, [], T0))).toBe(false);
  });
});

describe("abhaken ohne Netz und nachreichen", () => {
  it("merkt sich Änderungen mit Zeitstempel als ausstehend", () => {
    let saved = fromServer(null, "r", "schnell", shopping, serverItems, T0);
    expect(hasPending(saved)).toBe(false);
    saved = toggle(saved, "Rindshackfleisch", true, T1);
    saved = toggle(saved, "Mais", false, T1);
    expect(saved.items["Rindshackfleisch"]).toEqual({ checked: true, changed_at: T1 });
    expect(pendingItems(saved)).toEqual([
      { ingredient: "Rindshackfleisch", checked: true, changed_at: T1 },
      { ingredient: "Mais", checked: false, changed_at: T1 },
    ]);
  });

  it("übernimmt nach dem PATCH den Server-Stand und räumt nur Gesendetes auf", () => {
    let saved = fromServer(null, "r", "schnell", shopping, serverItems, T0);
    saved = toggle(saved, "Rindshackfleisch", true, T1);
    const sent = pendingItems(saved);
    // während des Sendens kommt eine weitere Änderung dazu
    saved = toggle(saved, "Zwiebel", true, T2);
    const fromApi: ChecklistItem[] = [
      { ingredient: "Rindshackfleisch", checked: true, changed_at: T1 },
      { ingredient: "Mais", checked: true, changed_at: "2026-11-08T10:00:00+01:00" },
      { ingredient: "Zwiebel", checked: false, changed_at: null }, // Server kennt Zwiebel noch nicht
    ];
    saved = acknowledge(saved, sent, fromApi, T2);
    expect(Object.keys(saved.pending)).toEqual(["Zwiebel"]);
    expect(saved.items["Zwiebel"]?.checked).toBe(true); // lokal neuer, bleibt sichtbar
    expect(saved.items["Rindshackfleisch"]?.checked).toBe(true);
  });

  it("lässt eine erneute Änderung derselben Zutat während des Sendens ausstehend", () => {
    let saved = fromServer(null, "r", "schnell", shopping, serverItems, T0);
    saved = toggle(saved, "Zwiebel", true, T1);
    const sent = pendingItems(saved);
    saved = toggle(saved, "Zwiebel", false, T2); // Haken wieder weg, bevor die Antwort da ist
    saved = acknowledge(saved, sent, [{ ingredient: "Zwiebel", checked: true, changed_at: T1 }], T2);
    expect(saved.pending["Zwiebel"]).toEqual({ checked: false, changed_at: T2 });
    expect(saved.items["Zwiebel"]?.checked).toBe(false);
  });
});

describe("Server-Stand übernehmen", () => {
  it("behält ausstehende Änderungen desselben Laufs, ersetzt bei anderem Lauf oder anderer Variante", () => {
    let saved = fromServer(null, "r1", "schnell", shopping, serverItems, T0);
    saved = toggle(saved, "Zwiebel", true, T1);
    const same = fromServer(saved, "r1", "schnell", shopping, serverItems, T2);
    expect(same.items["Zwiebel"]?.checked).toBe(true);
    expect(hasPending(same)).toBe(true);
    const other = fromServer(saved, "r2", "schnell", shopping, serverItems, T2);
    expect(hasPending(other)).toBe(false);
    expect(other.items["Zwiebel"]?.checked).toBe(false);
    const otherVariant = fromServer(saved, "r1", "budget", shopping, [], T2);
    expect(hasPending(otherVariant)).toBe(false);
  });
});
