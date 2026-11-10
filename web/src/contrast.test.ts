// Kontraste der Tokens in hell und dunkel (WCAG 2): Text 4.5:1, Bedienelemente und Fokus 3:1.
// Rechnet aus den echten Werten in tokens.css, nicht aus Schätzungen.
import { describe, expect, it } from "vitest";
import { contrastRatio, evaluate, loadTokens, parseTokens } from "../scripts/contrast.mjs";

describe("contrastRatio", () => {
  it("liefert die bekannten Referenzwerte", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 2);
    expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 2);
    expect(contrastRatio("#777777", "#FFFFFF")).toBeCloseTo(4.48, 2);
  });
});

describe("tokens.css", () => {
  const tokens = loadTokens();

  it("hat alle Farb-Rollen in hell und dunkel", () => {
    for (const scheme of ["light", "dark"] as const) {
      for (const name of ["bg", "surface", "surface-2", "ink", "ink-2", "line", "fuel", "on-fuel", "signal", "focus"]) {
        expect(tokens[scheme][name], `${scheme}: --${name}`).toMatch(/^#[0-9A-F]{6}$/);
      }
    }
  });

  it("erfüllt die Untergrenzen für jedes Paar", () => {
    const failed = evaluate(tokens).filter((r) => !r.ok);
    expect(failed.map((r) => `${r.scheme} ${r.fg}/${r.bg} ${r.ratio.toFixed(2)} < ${r.min}`)).toEqual([]);
  });

  it("ignoriert den prefers-contrast-Block beim Parsen", () => {
    const parsed = parseTokens(
      ":root{--ink:#111111;} @media (prefers-color-scheme: dark){:root{--ink:#EEEEEE;}}" +
        " @media (prefers-contrast: more){:root{--ink:#000000;} @media (prefers-color-scheme: dark){:root{--ink:#FFFFFF;}}}",
    );
    expect(parsed.light.ink).toBe("#111111");
    expect(parsed.dark.ink).toBe("#EEEEEE");
  });
});
