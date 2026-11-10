// Kontraste der Design-Tokens nach WCAG 2 (relative Luminanz, Verhältnis (L1+0.05)/(L2+0.05)).
// Aufruf: `npm run contrast` druckt die Tabelle; src/contrast.test.ts prüft dieselben Paare gegen die Untergrenzen.
// Keine Abhängigkeiten – nur Node.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function channel(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Liest tokens.css und liefert { light: {name: hex}, dark: {name: hex} } (nur Farb-Tokens, nur die Standardblöcke). */
export function parseTokens(css) {
  const blocks = /** @type {{ light: Record<string, string>, dark: Record<string, string> }} */ ({ light: {}, dark: {} });
  const base = stripBlock(css, "prefers-contrast"); // Hoch-Kontrast-Varianten (inkl. verschachteltem dark) nicht Teil der Grundprüfung
  const re = /(@media[^{]*\{\s*)?:root\s*\{([^}]*)\}/g;
  let m;
  while ((m = re.exec(base)) !== null) {
    const media = m[1] ?? "";
    const target = media.includes("dark") ? blocks.dark : blocks.light;
    for (const line of m[2].split(";")) {
      const kv = line.match(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})/);
      if (kv) target[kv[1]] = kv[2].toUpperCase();
    }
  }
  return blocks;
}

/** Entfernt jeden `@media (...<needle>...) { … }`-Block samt verschachtelter Klammern. */
export function stripBlock(css, needle) {
  let out = css;
  for (;;) {
    const start = out.search(new RegExp(`@media[^{]*${needle}[^{]*\\{`));
    if (start < 0) return out;
    let depth = 0;
    let i = out.indexOf("{", start);
    for (; i < out.length; i += 1) {
      if (out[i] === "{") depth += 1;
      else if (out[i] === "}") {
        depth -= 1;
        if (depth === 0) break;
      }
    }
    out = out.slice(0, start) + out.slice(i + 1);
  }
}

/** Die Paare, die im Interface wirklich vorkommen, mit Rolle und Untergrenze. */
export const PAIRS = [
  ["ink", "surface", "Text auf Karte", 4.5],
  ["ink", "bg", "Text auf Seite", 4.5],
  ["ink", "surface-2", "Text auf Vertiefung", 4.5],
  ["ink-2", "surface", "Nebentext auf Karte", 4.5],
  ["ink-2", "bg", "Nebentext auf Seite", 4.5],
  ["ink-2", "surface-2", "Nebentext auf Vertiefung", 4.5],
  ["fuel", "surface", "Akzent als Text/Symbol auf Karte", 4.5],
  ["fuel", "bg", "Akzent als Text/Symbol auf Seite (Tab aktiv)", 4.5],
  ["fuel", "surface-2", "Balkenfüllung gegen Spur (Bedienelement)", 3],
  ["on-fuel", "fuel", "Text auf primärem Button", 4.5],
  ["signal", "surface", "Fehlertext auf Karte", 4.5],
  ["signal", "bg", "Fehlertext auf Seite", 4.5],
  ["line", "surface", "Rahmen gegen Karte (dekorativ, Richtwert)", 1.2],
  ["surface", "bg", "Karte gegen Seite (dekorativ, Richtwert)", 1.0],
  ["focus", "surface", "Fokusring auf Karte", 3],
  ["focus", "bg", "Fokusring auf Seite", 3],
];

export function evaluate(tokens) {
  const rows = [];
  for (const scheme of ["light", "dark"]) {
    const t = tokens[scheme];
    for (const [fg, bg, role, min] of PAIRS) {
      const a = t[fg];
      const b = t[bg];
      if (!a || !b) {
        rows.push({ scheme, fg, bg, role, min, ratio: NaN, ok: false, a, b });
        continue;
      }
      const ratio = contrastRatio(a, b);
      rows.push({ scheme, fg, bg, role, min, ratio, ok: ratio >= min, a, b });
    }
  }
  return rows;
}

export function loadTokens() {
  const here = dirname(fileURLToPath(import.meta.url));
  return parseTokens(readFileSync(join(here, "..", "src", "tokens.css"), "utf8"));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const rows = evaluate(loadTokens());
  let failed = 0;
  for (const scheme of ["light", "dark"]) {
    console.log(`\n${scheme === "light" ? "Hell" : "Dunkel"}`);
    console.log("  Vordergrund      Hintergrund      Verhältnis  Min   Rolle");
    for (const r of rows.filter((x) => x.scheme === scheme)) {
      const ratio = Number.isNaN(r.ratio) ? "   –" : r.ratio.toFixed(2).padStart(5);
      const mark = r.ok ? "ok " : "FEHLT";
      if (!r.ok) failed += 1;
      console.log(`  ${(r.fg + " " + r.a).padEnd(17)}${(r.bg + " " + r.b).padEnd(17)}${ratio}:1     ${String(r.min).padEnd(4)}  ${mark}  ${r.role}`);
    }
  }
  console.log(failed ? `\n${failed} Paar(e) unter der Untergrenze.` : "\nAlle Paare über der Untergrenze.");
  process.exit(failed ? 1 : 0);
}
