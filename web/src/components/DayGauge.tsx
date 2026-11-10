// Tag-Typ und Bedarf: der Block, an den man sich erinnert. Training → Treibstoff fürs Abendessen.
import { fmtInt } from "../format";
import type { DayDTO } from "../types";
import { FuelBar } from "./FuelBar";

export function DayGauge({ day }: { day: DayDTO }) {
  const ctx = day.context;
  const needs = ctx.needs;
  const cls = ctx.classification;
  const dinner = day.dinner_target;
  const label = day.day_type_label ?? cls?.day_type ?? "–";
  const rest = cls?.day_type === "Ruhetag";

  return (
    <section className="card gauge" aria-labelledby="gauge-title">
      <p className="eyebrow">Tag-Typ</p>
      <h2 id="gauge-title" className="gauge-type">
        {label}
      </h2>
      {cls?.reason && <p className="gauge-reason">{cls.reason}</p>}

      {needs && dinner.kcal != null ? (
        <>
          <div className="gauge-kcal">
            <span className="gauge-kcal-number">{fmtInt(dinner.kcal)}</span>
            <span className="gauge-kcal-unit"> kcal</span>
            <p className="gauge-kcal-sub">
              fürs Abendessen · {dinner.share_pct ?? 40} % von {fmtInt(needs.kcal)} kcal am Tag
            </p>
          </div>
          <div className="gauge-bars">
            <FuelBar label="Kohlenhydrate" value={dinner.carbs_g ?? 0} max={needs.carbs_g} unit="g" maxLabel={`Tag ${fmtInt(needs.carbs_g)} g`} />
            <FuelBar label="Protein" value={dinner.protein_g ?? 0} max={needs.protein_g} unit="g" maxLabel={`Tag ${fmtInt(needs.protein_g)} g`} />
            <FuelBar label="Fett" value={dinner.fat_g ?? 0} max={needs.fat_g} unit="g" maxLabel={`Tag ${fmtInt(needs.fat_g)} g`} />
          </div>
          <p className="gauge-foot">
            {rest ? "Ruhetag: Grundbedarf, kein Zuschlag." : "Bedarf nach den Regeln in rules.py, keine Ernährungsberatung."}
            {ctx.week_load_avg_7d != null && ` Ø Trainingslast 7 Tage: ${fmtInt(ctx.week_load_avg_7d)}.`}
          </p>
        </>
      ) : (
        <p className="gauge-foot">Kein Bedarf berechnet.</p>
      )}
    </section>
  );
}
