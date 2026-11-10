// Tab „Einkauf“ (Schritt 5): Liste der gewählten Variante nach Laden gruppiert, Abhaken mit PATCH /checklist (changed_at),
// Summen pro Laden (aus der API) und gesamt, Aktionen mit Text. Offline: gespeicherte Liste aus offline.ts, Hinweis,
// Abhaken geht weiter, ausstehende Änderungen werden beim nächsten Kontakt nachgereicht (Konfliktregel macht der Server).
import { Check, CloudOff, RefreshCw, Tag } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, describeError, NetworkError } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Notice } from "../components/Notice";
import { chainLabel, fmtChf, fmtDateShort, fmtInt, sizeText, VARIANT_LABELS } from "../format";
import * as offline from "../offline";
import type { SavedShopping } from "../offline";
import type { ShoppingLine } from "../types";

type Phase = "loading" | "ready" | "empty" | "error";
const CHAIN_ORDER = ["migros", "denner", "coop"];
const RETRY_MS = 20_000;

const nowIso = () => new Date().toISOString();

export function Shopping({ goToday }: { goToday: () => void }) {
  const storage = useRef(offline.browserStorage()).current;
  const [saved, setSavedState] = useState<SavedShopping | null>(() => offline.load(storage));
  const savedRef = useRef(saved);
  const [phase, setPhase] = useState<Phase>(saved ? "ready" : "loading");
  const [online, setOnline] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);
  const [emptyReason, setEmptyReason] = useState<string | null>(null);
  const flushChain = useRef<Promise<void>>(Promise.resolve());

  const setSaved = useCallback(
    (next: SavedShopping | null) => {
      savedRef.current = next;
      setSavedState(next);
      offline.persist(storage, next);
    },
    [storage],
  );

  /** Ausstehende Änderungen an den Server schicken; die Antwort ist der zusammengeführte Stand. */
  const flush = useCallback(() => {
    flushChain.current = flushChain.current.then(async () => {
      const cur = savedRef.current;
      if (!cur || !offline.hasPending(cur)) return;
      const sent = offline.pendingItems(cur);
      try {
        const cl = await api.patchChecklist(cur.runId, sent);
        const latest = savedRef.current;
        if (latest && latest.runId === cur.runId && latest.variant === cur.variant) setSaved(offline.acknowledge(latest, sent, cl.items, nowIso()));
        setOnline(true);
        setError(null);
      } catch (e) {
        if (e instanceof NetworkError) {
          setOnline(false);
        } else {
          // Der Server lehnt die Änderung ab (z. B. Liste gewechselt): ausstehende Änderungen verwerfen, Stand neu laden
          setError(describeError(e));
          const latest = savedRef.current;
          if (latest) setSaved({ ...latest, pending: {} });
        }
      }
    });
    return flushChain.current;
  }, [setSaved]);

  const refresh = useCallback(async () => {
    setSyncing(true);
    try {
      await flush();
      const run = await api.latestRun();
      const chosen = run.status === "done" ? run.chosen_variant : null;
      const list = chosen ? run.shopping[chosen] : undefined;
      if (chosen && list) {
        const cl = await api.checklist(run.run_id);
        setSaved(offline.fromServer(savedRef.current, run.run_id, chosen, list, cl.items, nowIso()));
        setPhase("ready");
        setEmptyReason(null);
      } else if (savedRef.current && run.status === "running") {
        setPhase("ready"); // ein neuer Lauf läuft; die zuletzt gewählte Liste bleibt brauchbar
      } else {
        setPhase("empty");
        setEmptyReason(run.status === "running" ? "Ein Lauf läuft gerade. Wähle danach unter «Heute» ein Rezept." : null);
      }
      setOnline(true);
      setError(null);
    } catch (e) {
      if (e instanceof NetworkError) {
        setOnline(false);
        setPhase(savedRef.current ? "ready" : "error");
        if (!savedRef.current) setError(describeError(e));
      } else if (e instanceof ApiError && e.info.code === "no_run_today") {
        setOnline(true);
        setPhase("empty");
        setEmptyReason(null);
      } else {
        setOnline(true);
        setError(describeError(e));
        if (!savedRef.current) setPhase("error");
      }
    } finally {
      setSyncing(false);
    }
  }, [flush, setSaved]);

  useEffect(() => {
    void refresh();
    const onOnline = () => void refresh();
    const onVisible = () => document.visibilityState === "visible" && void refresh();
    window.addEventListener("online", onOnline);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("online", onOnline);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  // Offline: alle 20 s leise nachfragen, ob der Mac wieder da ist
  useEffect(() => {
    if (online) return;
    const t = window.setInterval(() => void refresh(), RETRY_MS);
    return () => window.clearInterval(t);
  }, [online, refresh]);

  const onToggle = (ingredient: string, checked: boolean) => {
    const cur = savedRef.current;
    if (!cur) return;
    setSaved(offline.toggle(cur, ingredient, checked, nowIso()));
    if (online) void flush();
  };

  const pendingCount = saved ? Object.keys(saved.pending).length : 0;

  return (
    <section className="page" aria-busy={phase === "loading"}>
      <header className="page-head page-head-row">
        <div>
          <p className="page-date">{saved ? `${VARIANT_LABELS[saved.variant]} · Lauf vom ${fmtDateShort(saved.runId.slice(0, 10))}` : "Einkaufsliste"}</p>
          <h1 className="page-title">Einkauf</h1>
        </div>
        {saved && phase === "ready" && (
          <p className="page-counter" aria-live="polite">
            <strong>{offline.checkedCount(saved)}</strong> von {saved.shopping.lines.length}
          </p>
        )}
      </header>

      {!online && (
        <div className="banner" role="status">
          <CloudOff className="notice-icon" aria-hidden="true" />
          <div className="notice-body">
            <p className="notice-title">Offline – wird abgeglichen, sobald der Mac erreichbar ist</p>
            <p className="notice-text">
              {pendingCount > 0 ? `${pendingCount} ${pendingCount === 1 ? "Änderung wartet" : "Änderungen warten"} auf den Abgleich. ` : ""}
              Abhaken geht weiter.
            </p>
            <button type="button" className="btn btn-secondary" onClick={() => void refresh()} disabled={syncing}>
              <RefreshCw className="inline-icon" aria-hidden="true" />
              {syncing ? "Verbinde …" : "Jetzt abgleichen"}
            </button>
          </div>
        </div>
      )}

      {error && online && (
        <Notice kind="error" title={error.title} action={{ label: "Nochmals laden", onClick: () => void refresh(), busy: syncing }}>
          <p>{error.hint}</p>
        </Notice>
      )}

      {phase === "loading" && (
        <div className="card skeleton" aria-hidden="true">
          <div className="skeleton-line w40" />
          <div className="skeleton-line w70" />
          <div className="skeleton-line w55" />
        </div>
      )}

      {phase === "empty" && (
        <EmptyState
          title="Noch keine Variante gewählt"
          text={emptyReason ?? "Wähle unter «Heute» ein Rezept. Die Einkaufsliste erscheint dann hier, nach Laden gruppiert."}
          action={{ label: "Zu Heute", onClick: goToday }}
        />
      )}

      {phase === "ready" && saved && <ShoppingView saved={saved} onToggle={onToggle} />}
    </section>
  );
}

function ShoppingView({ saved, onToggle }: { saved: SavedShopping; onToggle: (ingredient: string, checked: boolean) => void }) {
  const sl = saved.shopping;
  const groups: { key: string; label: string; lines: ShoppingLine[]; total: number | null; estimated: boolean }[] = [];
  for (const chain of CHAIN_ORDER) {
    const lines = sl.lines.filter((l) => l.product?.chain === chain);
    if (lines.length) groups.push({ key: chain, label: chainLabel(chain), lines, total: sl.store_totals?.[chain] ?? null, estimated: sl.store_has_estimates?.[chain] ?? false });
  }
  const without = sl.lines.filter((l) => !l.product);
  if (without.length) groups.push({ key: "none", label: "Ohne Produkt", lines: without, total: null, estimated: true });

  return (
    <>
      <section className="card summary" aria-label="Summe">
        <p className="summary-title">{sl.recipe_name}</p>
        <div className="summary-row">
          <div>
            <p className="summary-label">Einkauf gesamt</p>
            <p className="summary-value">
              {fmtChf(sl.total_chf)} <span className="price-unit">CHF</span>
            </p>
            <p className="summary-note">ganze Packungen{sl.has_estimates ? " · enthält geschätzte Preise" : ""}</p>
          </div>
          <div>
            <p className="summary-label">Pro Portion</p>
            <p className="summary-value">
              {fmtChf(sl.price_per_portion_chf)} <span className="price-unit">CHF</span>
            </p>
            <p className="summary-note">
              anteilig {fmtChf(sl.proportional_total_chf)} CHF{sl.portions > 1 ? ` für ${sl.portions} Portionen` : ""}
            </p>
          </div>
        </div>
        {sl.promotions > 0 && (
          <p className="summary-note promo">
            <Tag className="inline-icon" aria-hidden="true" /> {sl.promotions === 1 ? "1 Aktion" : `${sl.promotions} Aktionen`} auf der Liste
          </p>
        )}
      </section>

      {groups.map((g) => (
        <section key={g.key} className="store" aria-labelledby={`store-${g.key}`}>
          <header className="store-head">
            <h2 id={`store-${g.key}`} className="store-name">
              {g.label}
            </h2>
            <p className="store-total">
              {g.total != null ? (
                <>
                  <strong>{fmtChf(g.total)}</strong> CHF{g.estimated ? <span className="muted"> · teils geschätzt</span> : null}
                </>
              ) : (
                <span className="muted">nur Schätzung</span>
              )}
            </p>
          </header>
          <ul className="rows">
            {g.lines.map((line) => {
              const st = saved.items[line.ingredient];
              const checked = st?.checked ?? false;
              return (
                <li key={line.ingredient}>
                  <button type="button" role="checkbox" aria-checked={checked} className={checked ? "row is-checked" : "row"} onClick={() => onToggle(line.ingredient, !checked)}>
                    <span className="row-check" aria-hidden="true">
                      {checked && <Check strokeWidth={3} />}
                    </span>
                    <span className="row-body">
                      <span className="row-title">
                        <span className="row-ingredient">{line.ingredient}</span>
                        <span className="row-grams muted"> · {fmtInt(line.grams)} g</span>
                      </span>
                      {line.product ? (
                        <span className="row-product">
                          {line.product.name}
                          {line.product.brand && !line.product.name.includes(line.product.brand) ? ` (${line.product.brand})` : ""}
                          <span className="muted">
                            {" · "}
                            {sizeText(line.product)}
                            {line.packs > 1 ? ` · ${line.packs} ×` : ""}
                          </span>
                        </span>
                      ) : (
                        <span className="row-product muted">Kein passendes Produkt gefunden – Preis geschätzt</span>
                      )}
                      {(line.promotion || line.product?.note || line.note) && (
                        <span className="row-flags">
                          {line.promotion && (
                            <span className="flag">
                              <Tag className="inline-icon" aria-hidden="true" />
                              Aktion
                              {line.product?.regular_price_chf != null ? ` · statt ${fmtChf(line.product.regular_price_chf)}` : ""}
                            </span>
                          )}
                          {(line.product?.note || line.note) && <span className="muted">{line.product?.note ?? line.note}</span>}
                        </span>
                      )}
                    </span>
                    <span className="row-price">
                      <span className="row-total">{line.product ? fmtChf(line.total_chf) : line.price_each_chf > 0 ? fmtChf(line.price_each_chf) : "–"}</span>
                      {line.estimated && <span className="row-est">geschätzt</span>}
                      {line.packs > 1 && line.product && <span className="muted">{fmtChf(line.price_each_chf)} je</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {sl.warnings.length > 0 && (
        <Notice title="Hinweise">
          <ul className="plain-list">
            {sl.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Notice>
      )}
      <p className="run-meta">
        Liste gespeichert {fmtDateShort(saved.savedAt.slice(0, 10))} · bleibt ohne Verbindung nutzbar
      </p>
    </>
  );
}
