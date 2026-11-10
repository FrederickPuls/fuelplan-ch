import { describe, expect, it } from "vitest";
import { fmtChf, fmtDateLong, fmtDateShort, fmtInt, fmtKm, fmtMinutes, fmtMonth, fmtTime, share, sizeText, warningsFor } from "./format";

describe("Zahlenformate (de-CH)", () => {
  it("gruppiert Tausender mit Apostroph", () => {
    expect(fmtInt(3050)).toBe("3’050");
    expect(fmtInt(726)).toBe("726");
  });
  it("zeigt CHF mit zwei Stellen und Dezimalpunkt", () => {
    expect(fmtChf(4.37)).toBe("4.37");
    expect(fmtChf(5.9)).toBe("5.90");
    expect(fmtChf(31.85)).toBe("31.85");
  });
  it("zeigt Kilometer mit mindestens einer Stelle", () => {
    expect(fmtKm(10.07)).toBe("10.07 km");
    expect(fmtKm(5)).toBe("5.0 km");
  });
  it("formatiert Minuten und Stunden", () => {
    expect(fmtMinutes(55)).toBe("55 min");
    expect(fmtMinutes(60)).toBe("1 h");
    expect(fmtMinutes(125)).toBe("2 h 5 min");
  });
  it("kürzt Zeiten auf hh:mm", () => {
    expect(fmtTime("13:00:00")).toBe("13:00");
    expect(fmtTime(null)).toBe("");
  });
});

describe("Datum", () => {
  it("schreibt das Datum lang und kurz aus, ohne Zeitzone", () => {
    expect(fmtDateLong("2026-11-07")).toBe("Samstag, 7. November 2026");
    expect(fmtDateShort("2026-11-07")).toBe("7.11.2026");
  });
});

describe("share", () => {
  it("begrenzt auf 0…1 und verträgt 0 als Maximum", () => {
    expect(share(161, 402)).toBeCloseTo(0.4, 2);
    expect(share(500, 402)).toBe(1);
    expect(share(10, 0)).toBe(0);
    expect(share(-5, 10)).toBe(0);
  });
});

describe("warningsFor", () => {
  it("filtert nach Variante und entfernt das Präfix", () => {
    const all = ["budget: Preis aus Cache (geschätzt): Reis", "schnell: KH 132 g weicht -18% ab", "Variante aufwendig fehlt"];
    expect(warningsFor("budget", all)).toEqual(["Preis aus Cache (geschätzt): Reis"]);
    expect(warningsFor("schnell", all)).toEqual(["KH 132 g weicht -18% ab"]);
    expect(warningsFor("aufwendig", all)).toEqual([]);
  });
});

describe("sizeText", () => {
  it("formatiert Packungsgrössen wie das CLI", () => {
    expect(sizeText({ size_value: 500, size_unit: "g" })).toBe("500 g");
    expect(sizeText({ size_value: 1, size_unit: "l" })).toBe("1 l");
    expect(sizeText({ size_value: 6, size_unit: "piece" })).toBe("6 Stk");
    expect(sizeText({ size_value: 0.5, size_unit: "kg" })).toBe("0.5 kg");
    expect(sizeText({ size_value: null, size_unit: null })).toBe("–");
  });
});

describe("fmtMonth", () => {
  it("schreibt den Monat aus", () => {
    expect(fmtMonth("2026-11")).toBe("November 2026");
  });
});
