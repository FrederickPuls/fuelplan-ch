// Die Signatur der App: ein Treibstoff-Balken. Spur = Bezugsgrösse, Füllung = Anteil.
// Auf „Heute“: Spur = Tagesbedarf, Füllung = Anteil fürs Abendessen.
// Auf den Variantenkarten: Spur = Ziel fürs Abendessen, Füllung = was das Rezept liefert.
// Zahlen stehen immer daneben – die Farbe trägt nie allein.
import { fmtInt, share } from "../format";

export function FuelBar({
  label,
  value,
  max,
  unit,
  maxLabel,
  small = false,
  estimated = false,
}: {
  label: string;
  value: number;
  max: number;
  unit: string;
  /** Text für die Bezugsgrösse, z. B. "Tag 402 g" oder "Ziel 161 g" */
  maxLabel: string;
  small?: boolean;
  estimated?: boolean;
}) {
  const pct = Math.round(share(value, max) * 100);
  const over = max > 0 && value > max;
  const a11y = `${label}: ${fmtInt(value)} ${unit}${estimated ? " geschätzt" : ""}, ${maxLabel}${over ? ", über der Bezugsgrösse" : ""}`;
  return (
    <div className={small ? "fuel fuel-small" : "fuel"} role="img" aria-label={a11y}>
      <div className="fuel-row">
        <span className="fuel-label">{label}</span>
        <span className="fuel-value">
          <strong>{fmtInt(value)}</strong> {unit}
          {estimated && <span className="fuel-est"> geschätzt</span>}
        </span>
        <span className="fuel-max">{maxLabel}</span>
      </div>
      <div className="fuel-track" aria-hidden="true">
        <div className={over ? "fuel-fill is-over" : "fuel-fill"} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
