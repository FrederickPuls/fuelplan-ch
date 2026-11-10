// Tab „Verlauf“ (Schritt 5): Archiv aus history/recipes.jsonl, pro Eintrag „Gekocht?“ (ja/nein) und Bewertung 1–5
// über PATCH /api/history/{key}; Antippen des Namens öffnet das Rezept aus dem Run-Ordner.
import { ChevronRight, Star } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError, describeError } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Notice } from "../components/Notice";
import { RecipeSheet } from "../components/RecipeSheet";
import { fmtChf, fmtDateLong, VARIANT_LABELS } from "../format";
import type { HistoryEntry, RunResult } from "../types";

type Described = ReturnType<typeof describeError>;

export function History() {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<Described | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<{ run: RunResult; variant: HistoryEntry["record"]["variant"] } | null>(null);
  const [opening, setOpening] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try {
      setEntries(await api.history());
    } catch (e) {
      setError(describeError(e));
      setEntries([]);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const update = async (entry: HistoryEntry, body: { cooked?: boolean; rating?: number }) => {
    const before = entries ?? [];
    setEntries(before.map((e) => (e.key === entry.key ? { ...e, record: { ...e.record, ...body } } : e)));
    setRowError((r) => ({ ...r, [entry.key]: "" }));
    try {
      const changed = await api.patchHistory(entry.key, body);
      setEntries((cur) => (cur ?? []).map((e) => (e.key === entry.key ? changed : e)));
    } catch (e) {
      setEntries(before);
      setRowError((r) => ({ ...r, [entry.key]: describeError(e).hint }));
    }
  };

  const openRecipe = async (entry: HistoryEntry) => {
    if (!entry.record.run_dir) {
      setRowError((r) => ({ ...r, [entry.key]: "Zu diesem Eintrag gibt es keinen Run-Ordner." }));
      return;
    }
    setOpening(entry.key);
    try {
      const run = await api.run(entry.record.run_dir);
      if (run.status !== "done" || !run.recipes.some((r) => r.variant === entry.record.variant)) {
        setRowError((r) => ({ ...r, [entry.key]: "Das Rezept liegt nicht mehr im Run-Ordner." }));
        return;
      }
      setOpen({ run, variant: entry.record.variant });
    } catch (e) {
      const d = describeError(e);
      setRowError((r) => ({ ...r, [entry.key]: e instanceof ApiError && e.status === 404 ? "Der Run-Ordner dieses Laufs fehlt." : d.hint }));
    } finally {
      setOpening(null);
    }
  };

  const openRecipeObj = open ? open.run.recipes.find((r) => r.variant === open.variant) : null;

  return (
    <section className="page" aria-busy={entries === null}>
      <header className="page-head">
        <p className="page-date">Archiv</p>
        <h1 className="page-title">Verlauf</h1>
      </header>

      {error && (
        <Notice kind="error" title={error.title} action={{ label: "Nochmals laden", onClick: () => void load() }}>
          <p>{error.hint}</p>
        </Notice>
      )}

      {entries === null && (
        <div className="card skeleton" aria-hidden="true">
          <div className="skeleton-line w40" />
          <div className="skeleton-line w70" />
        </div>
      )}

      {entries && entries.length === 0 && !error && (
        <EmptyState title="Noch keine Einträge" text="Sobald du unter «Heute» eine Variante kochst, erscheint sie hier mit Datum, Preis und Bewertung." />
      )}

      {entries && entries.length > 0 && (
        <ul className="history">
          {entries.map((entry) => {
            const r = entry.record;
            return (
              <li key={entry.key} className="card history-item">
                <p className="eyebrow">
                  {fmtDateLong(r.date)} · {VARIANT_LABELS[r.variant]}
                  {r.dry_run && <span className="tag">Dry-Run</span>}
                </p>
                <button type="button" className="history-name" onClick={() => void openRecipe(entry)} disabled={opening === entry.key} aria-label={`Rezept öffnen: ${r.name}`}>
                  <span>{r.name}</span>
                  <ChevronRight aria-hidden="true" />
                </button>
                <p className="history-facts muted">
                  {r.price_chf_per_portion != null && <span>{fmtChf(r.price_chf_per_portion)} CHF pro Portion · </span>}
                  {r.main_ingredients.join(", ")}
                </p>

                <div className="history-controls">
                  <div className="control-group" role="group" aria-label="Gekocht?">
                    <span className="control-label">Gekocht?</span>
                    <button type="button" className={r.cooked === true ? "pill is-on" : "pill"} aria-pressed={r.cooked === true} onClick={() => void update(entry, { cooked: true })}>
                      Ja
                    </button>
                    <button type="button" className={r.cooked === false ? "pill is-on" : "pill"} aria-pressed={r.cooked === false} onClick={() => void update(entry, { cooked: false })}>
                      Nein
                    </button>
                  </div>
                  <div className="control-group" role="group" aria-label="Bewertung">
                    <span className="control-label">Bewertung</span>
                    <span className="stars">
                      {[1, 2, 3, 4, 5].map((n) => {
                        const on = (r.rating ?? 0) >= n;
                        return (
                          <button key={n} type="button" className={on ? "star is-on" : "star"} aria-label={`${n} von 5`} aria-pressed={r.rating === n} onClick={() => void update(entry, { rating: n })}>
                            <Star aria-hidden="true" fill={on ? "currentColor" : "none"} />
                          </button>
                        );
                      })}
                    </span>
                    <span className="control-value">{r.rating ? `${r.rating} von 5` : "offen"}</span>
                  </div>
                </div>
                {rowError[entry.key] && (
                  <p className="row-error" role="alert">
                    {rowError[entry.key]}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {open && openRecipeObj && <RecipeSheet run={open.run} recipe={openRecipeObj} onClose={() => setOpen(null)} readOnly />}
    </section>
  );
}
