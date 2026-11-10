// Kosten-Sheet aus /api/usage: Monatskosten gegen das Budget, Aufrufe pro Lauf, Restguthaben laut OpenRouter
// (im Dry-Run nicht abgefragt). Keine Rechnung hier – alle Zahlen kommen aus month_summary bzw. credits.
import { useEffect, useState } from "react";
import { api, describeError } from "../api";
import { fmtInt, fmtMonth, fmtUsd, share } from "../format";
import type { UsageResponse } from "../types";
import { Notice } from "./Notice";
import { Sheet } from "./Sheet";

interface RunUsage {
  calls: number;
  cost_usd: number;
  tokens: number;
  labels: string[];
}

export function CostsSheet({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);

  useEffect(() => {
    let alive = true;
    api.usage().then((d) => alive && setData(d)).catch((e) => alive && setError(describeError(e)));
    return () => {
      alive = false;
    };
  }, []);

  const s = data?.summary as
    | { calls?: number; runs?: Record<string, RunUsage>; total_cost_usd?: number; estimated_calls?: number; budget_usd?: number; budget_left_usd?: number; budget_pct?: number | null }
    | undefined;
  const credits = data?.credits as { limit?: number; usage?: number; limit_remaining?: number; total_credits?: number; total_usage?: number } | null | undefined;
  const runs = Object.entries(s?.runs ?? {}).sort(([a], [b]) => (a < b ? 1 : -1));

  return (
    <Sheet titleId="costs-title" onClose={onClose} testId="costs-sheet" head={<p className="eyebrow">Kosten</p>}>
      <h2 id="costs-title" className="sheet-title">
        {data ? fmtMonth(data.month) : "Kosten"}
      </h2>

      {!data && !error && (
        <div className="skeleton" aria-hidden="true">
          <div className="skeleton-line w40" />
          <div className="skeleton-line w70" />
        </div>
      )}

      {error && (
        <Notice kind="error" title={error.title}>
          <p>{error.hint}</p>
        </Notice>
      )}

      {data && s && (
        <>
          <div className="budget">
            <p className="budget-line">
              <span className="price-number">{fmtUsd(s.total_cost_usd ?? 0)}</span>
              <span className="price-unit"> USD</span>
              <span className="muted"> von {fmtUsd(s.budget_usd ?? 0)} USD Monatsbudget</span>
            </p>
            <div className="budget-track" role="img" aria-label={`${s.budget_pct ?? 0} % des Monatsbudgets verbraucht`}>
              <div className="budget-fill" style={{ width: `${Math.round(share(s.total_cost_usd ?? 0, s.budget_usd ?? 0) * 100)}%` }} />
            </div>
            <p className="muted">
              {s.budget_pct ?? 0} % verbraucht · Rest {fmtUsd(s.budget_left_usd ?? 0)} USD · {fmtInt(s.calls ?? 0)} Aufrufe in {runs.length} Läufen
              {s.estimated_calls ? ` · ${s.estimated_calls} mit geschätzten Kosten` : ""}
            </p>
          </div>

          <h3 className="sheet-section">Restguthaben laut OpenRouter</h3>
          {credits ? (
            <dl className="facts">
              <div>
                <dt>Key-Limit</dt>
                <dd>
                  {fmtUsd(credits.limit ?? 0)} USD · verbraucht {fmtUsd(credits.usage ?? 0, true)} USD · Rest {fmtUsd(credits.limit_remaining ?? 0, true)} USD
                </dd>
              </div>
              <div>
                <dt>Guthaben gesamt</dt>
                <dd>
                  {fmtUsd(credits.total_credits ?? 0)} USD · davon verbraucht {fmtUsd(credits.total_usage ?? 0, true)} USD
                </dd>
              </div>
            </dl>
          ) : (
            <p className="muted">{data.credits_note ?? "Restguthaben nicht abgefragt."}</p>
          )}

          <h3 className="sheet-section">Läufe diesen Monat</h3>
          {runs.length === 0 ? (
            <p className="muted">Noch keine Modellaufrufe in diesem Monat.</p>
          ) : (
            <ul className="runs">
              {runs.map(([name, r]) => (
                <li key={name}>
                  <span className="runs-name">{name}</span>
                  <span className="runs-facts muted">
                    {r.calls} {r.calls === 1 ? "Aufruf" : "Aufrufe"} · {fmtInt(r.tokens)} Tokens
                  </span>
                  <span className="runs-cost">{fmtUsd(r.cost_usd, true)} USD</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Sheet>
  );
}
