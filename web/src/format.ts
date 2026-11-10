// Anzeigeformate (Schweiz): Tausender mit Apostroph, Dezimalpunkt, CHF mit zwei Stellen. Reine Darstellung.

import type { Step, Variant } from "./types";

const APOS = "’"; // typografischer Apostroph als Tausendertrenner (Schweiz); fest, damit Node und Safari gleich formatieren

function group(intPart: string): string {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, APOS);
}

/** 3050 → "3’050" */
export function fmtInt(n: number): string {
  const r = Math.round(n);
  return (r < 0 ? "-" : "") + group(String(Math.abs(r)));
}

/** 4.37 → "4.37" (ohne Währung; die steht als Text daneben), 1234.5 → "1’234.50" */
export function fmtChf(n: number): string {
  const [i, d] = Math.abs(n).toFixed(2).split(".");
  return (n < 0 ? "-" : "") + group(i ?? "0") + "." + d;
}

/** 10.07 → "10.07 km", 5 → "5.0 km" */
export function fmtKm(km: number): string {
  const rounded = Math.round(km * 100) / 100;
  const s = Number.isInteger(rounded) ? rounded.toFixed(1) : String(rounded);
  return `${s} km`;
}

/** 55 → "55 min", 125 → "2 h 5 min" */
export function fmtMinutes(min: number): string {
  const m = Math.round(min);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

/** "13:00:00" → "13:00" */
export const fmtTime = (t?: string | null): string => (t ? t.slice(0, 5) : "");

const WEEKDAYS = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

/** "2026-11-07" → "Samstag, 7. November 2026" (ohne Zeitzonen-Umrechnung). */
export function fmtDateLong(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const date = new Date(y, m - 1, d);
  return `${WEEKDAYS[date.getDay()]}, ${d}. ${MONTHS[m - 1]} ${y}`;
}

/** "2026-11-07" → "7.11.2026" */
export function fmtDateShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

export const VARIANT_LABELS: Record<Variant, string> = { budget: "Budget", schnell: "Schnell", aufwendig: "Aufwendig" };

export const TYPE_LABELS: Record<string, string> = {
  running: "Lauf",
  strength_training: "Kraft",
  cycling: "Rad",
  hiking: "Wandern",
  other: "Surf",
  unknown: "Training",
};

export const typeLabel = (type: string): string => TYPE_LABELS[type] ?? type;

export const STEP_LABELS: Record<Step, string> = {
  collect: "Training lesen",
  plan: "Rezepte planen",
  retrieve: "Preise suchen",
  execute: "Produkte wählen",
  compute: "Preise rechnen",
  done: "Fertig",
};

/** Anteil für eine Balkenbreite, auf 0…1 begrenzt (nur Darstellung). */
export function share(value: number, max: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(max) || max <= 0) return 0;
  return Math.max(0, Math.min(1, value / max));
}

/** Warnungen einer Variante aus der Gesamtliste: Präfix "budget: " entfernen, andere Varianten weglassen. */
export function warningsFor(variant: Variant, warnings: string[]): string[] {
  const prefix = `${variant}: `;
  return warnings.filter((w) => w.startsWith(prefix)).map((w) => w.slice(prefix.length));
}

export const CHAIN_LABELS: Record<string, string> = { migros: "Migros", denner: "Denner", coop: "Coop" };
export const chainLabel = (chain: string): string => CHAIN_LABELS[chain] ?? chain;

/** Packungsgrösse wie im CLI: 500 g, 1 l, 6 Stk; ohne Angabe „–“. */
export function sizeText(p: { size_value?: number | null; size_unit?: string | null }): string {
  if (p.size_value == null || !p.size_unit) return "–";
  const v = Number.isInteger(p.size_value) ? String(p.size_value) : String(Math.round(p.size_value * 100) / 100);
  const unit = p.size_unit.toLowerCase();
  if (unit === "piece" || unit === "pieces" || unit === "stk" || unit === "stück") return `${v} Stk`;
  return `${v} ${p.size_unit}`;
}

/** 0.2794 → "0.28", 9.720585 → "9.72" (USD mit zwei Stellen); kleine Beträge mit vier Stellen. */
export function fmtUsd(n: number, precise = false): string {
  return precise ? n.toFixed(4) : fmtChf(n);
}

/** "2026-11" → "November 2026" */
export function fmtMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  if (!y || !m) return ym;
  return `${MONTHS[m - 1]} ${y}`;
}
