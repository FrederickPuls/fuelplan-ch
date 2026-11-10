import { Bike, Dumbbell, Footprints, Mountain, Waves } from "lucide-react";
import { fmtInt, fmtKm, fmtMinutes, fmtTime, typeLabel } from "../format";
import type { Activity } from "../types";

function iconFor(type: string) {
  switch (type) {
    case "running":
      return Footprints;
    case "strength_training":
      return Dumbbell;
    case "cycling":
      return Bike;
    case "hiking":
      return Mountain;
    default:
      return Waves;
  }
}

export function TrainingList({ activities, source }: { activities: Activity[]; source: string }) {
  return (
    <section className="card" aria-labelledby="training-title">
      <div className="card-head">
        <h2 id="training-title" className="card-title">
          Training heute
        </h2>
        <span className="card-meta">{source}</span>
      </div>
      {activities.length === 0 ? (
        <p className="muted">Kein Training aufgezeichnet.</p>
      ) : (
        <ul className="training-list">
          {activities.map((a, i) => {
            const Icon = iconFor(a.type);
            const facts = [
              fmtMinutes(a.duration_min),
              a.distance_km ? fmtKm(a.distance_km) : null,
              a.avg_hr != null ? `Ø ${fmtInt(a.avg_hr)} bpm` : null,
              a.kcal != null ? `${fmtInt(a.kcal)} kcal` : null,
              a.training_load != null ? `Last ${fmtInt(a.training_load)}` : null,
            ].filter(Boolean);
            return (
              <li key={a.external_id ?? i} className="training">
                <span className="training-icon" aria-hidden="true">
                  <Icon strokeWidth={1.9} />
                </span>
                <div className="training-body">
                  <p className="training-title">
                    <span className="training-type">{typeLabel(a.type)}</span>
                    {a.time && <span className="training-time"> · {fmtTime(a.time)}</span>}
                  </p>
                  {a.name && <p className="training-name">{a.name}</p>}
                  <p className="training-facts">{facts.join(" · ")}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
