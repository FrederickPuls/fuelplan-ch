// Tab „Heute“ (Block 2): alle Zustände und die Wiederaufnahme.
//   loading → idle (kein Lauf heute: Training, Tag-Typ, Bedarf, Button)
//           → running (SSE-Stufen; bei visibilitychange pausieren und ab lastEventId neu verbinden)
//           → done (drei Karten, Rezept-Sheet, „Diese Variante kochen“ → Einkauf)
//           → failed (Fehler des Laufs als HTTP 200 mit status "error", Fehler direkter Routen, Mac nicht erreichbar)
// Ein zweiter Start während eines Laufs → 409 mit run_id → an den laufenden Lauf hängen.
import { Wallet } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, describeError } from "../api";
import { CostsSheet } from "../components/CostsSheet";
import { DayGauge } from "../components/DayGauge";
import { Notice } from "../components/Notice";
import { RecipeSheet } from "../components/RecipeSheet";
import { TrainingList } from "../components/TrainingList";
import { VariantCard } from "../components/VariantCard";
import { fmtChf, fmtDateLong, fmtInt, STEP_LABELS, warningsFor } from "../format";
import { RunStream, type RunEvent } from "../sse";
import type { DayDTO, ErrorInfo, RunResult, Step, Variant } from "../types";

type Described = ReturnType<typeof describeError>;

type Phase =
  | { kind: "loading" }
  | { kind: "idle" }
  | { kind: "running"; runId: string; step: Step | null; detail: string | null; log: string | null; connection: "live" | "reconnecting" }
  | { kind: "done"; run: RunResult }
  | { kind: "failed"; error: Described; runId: string | null; retry: "load" | "start" };

const RECONCILE_MS = 2500;

function errorOfRun(run: RunResult): ErrorInfo {
  return run.error ?? { code: run.status, message: "Der Lauf ist nicht abgeschlossen." };
}

export function Today({ onChosen }: { onChosen?: (variant: Variant) => void }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [day, setDay] = useState<DayDTO | null>(null);
  const [starting, setStarting] = useState(false);
  const [openVariant, setOpenVariant] = useState<Variant | null>(null);
  const [costsOpen, setCostsOpen] = useState(false);
  const stream = useRef<RunStream | null>(null);
  const reconcileTimer = useRef<number | null>(null);

  const stopStream = useCallback(() => {
    stream.current?.close();
    stream.current = null;
    if (reconcileTimer.current != null) {
      window.clearTimeout(reconcileTimer.current);
      reconcileTimer.current = null;
    }
  }, []);

  /** Tagesanalyse nachladen, wenn der Lauf keine liefert (Fehler, laufend) – rein zur Anzeige. */
  const ensureDay = useCallback(async () => {
    try {
      setDay(await api.day());
    } catch {
      // ohne Tagesanalyse weiter; der eigentliche Fehler wird separat gezeigt
    }
  }, []);

  /** Ergebnis eines Laufs in einen Zustand übersetzen; true, wenn der Lauf abgeschlossen ist. */
  const showRun = useCallback(
    (run: RunResult): boolean => {
      if (run.status === "done") {
        stopStream();
        if (run.day) setDay(run.day);
        setPhase({ kind: "done", run });
        return true;
      }
      if (run.status === "running") {
        setPhase((p) =>
          p.kind === "running" && p.runId === run.run_id
            ? { ...p, step: run.step ?? p.step }
            : { kind: "running", runId: run.run_id, step: run.step ?? null, detail: null, log: null, connection: "live" },
        );
        return false;
      }
      stopStream();
      setPhase({ kind: "failed", error: describeError(new ApiError(200, errorOfRun(run))), runId: run.run_id, retry: "start" });
      return true;
    },
    [stopStream],
  );

  const reconcile = useCallback(
    (runId: string) => {
      if (reconcileTimer.current != null) window.clearTimeout(reconcileTimer.current);
      reconcileTimer.current = window.setTimeout(async () => {
        reconcileTimer.current = null;
        try {
          showRun(await api.run(runId));
        } catch (e) {
          setPhase({ kind: "failed", error: describeError(e), runId, retry: "load" });
        }
      }, RECONCILE_MS);
    },
    [showRun],
  );

  const attach = useCallback(
    (runId: string) => {
      if (stream.current?.runId === runId && stream.current.active) {
        stream.current.open();
        return;
      }
      stopStream();
      const onEvent = (e: RunEvent) => {
        switch (e.type) {
          case "step":
            setPhase((p) => (p.kind === "running" ? { ...p, step: e.step, detail: e.detail, connection: "live" } : p));
            break;
          case "log":
            setPhase((p) => (p.kind === "running" ? { ...p, log: e.text, connection: "live" } : p));
            break;
          case "done":
            void api.run(runId).then(showRun, (err) => setPhase({ kind: "failed", error: describeError(err), runId, retry: "load" }));
            break;
          case "error":
            setPhase({ kind: "failed", error: describeError(new ApiError(e.status ?? 200, e.info)), runId, retry: "start" });
            break;
          case "incomplete":
            setPhase({
              kind: "failed",
              error: describeError(new ApiError(200, e.info ?? { code: "incomplete", message: "Dieser Lauf ist unvollständig. Bitte einen neuen Lauf starten." })),
              runId,
              retry: "start",
            });
            break;
        }
      };
      const s = new RunStream(runId, onEvent, {
        onConnectionError: () => {
          setPhase((p) => (p.kind === "running" ? { ...p, connection: "reconnecting" } : p));
          reconcile(runId); // der Lauf kann inzwischen fertig sein
        },
      });
      stream.current = s;
      s.open();
    },
    [reconcile, showRun, stopStream],
  );

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setPhase({ kind: "loading" });
      try {
        const run = await api.latestRun();
        const finished = showRun(run);
        if (!finished) {
          attach(run.run_id);
          if (!day) void ensureDay();
        } else if (run.status !== "done") {
          void ensureDay();
        }
        return;
      } catch (e) {
        if (!(e instanceof ApiError && e.info.code === "no_run_today")) {
          setPhase({ kind: "failed", error: describeError(e), runId: null, retry: "load" });
          return;
        }
      }
      try {
        setDay(await api.day());
        setPhase({ kind: "idle" });
      } catch (e) {
        setPhase({ kind: "failed", error: describeError(e), runId: null, retry: "load" });
      }
    },
    [attach, day, ensureDay, showRun],
  );

  // Start und Aufräumen
  useEffect(() => {
    void load();
    return stopStream;
  }, []);

  // Sichtbarkeit: im Hintergrund Verbindung schliessen, beim Zurückkommen ab lastEventId neu verbinden und Stand nachfragen
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        stream.current?.pause();
        return;
      }
      if (stream.current?.active) {
        stream.current.open();
        reconcile(stream.current.runId);
      } else if (phase.kind !== "loading") {
        void load(true);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [load, phase.kind, reconcile]);

  const start = async () => {
    setStarting(true);
    try {
      const started = await api.startRun();
      setPhase({ kind: "running", runId: started.run_id, step: null, detail: null, log: null, connection: "live" });
      attach(started.run_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.info.run_id) {
        setPhase({ kind: "running", runId: e.info.run_id, step: null, detail: null, log: null, connection: "live" });
        attach(e.info.run_id);
      } else {
        setPhase({ kind: "failed", error: describeError(e), runId: null, retry: "start" });
      }
    } finally {
      setStarting(false);
    }
  };

  const dateIso = day?.date ?? new Date().toISOString().slice(0, 10);
  const run = phase.kind === "done" ? phase.run : null;
  const openRecipe = run && openVariant ? run.recipes.find((r) => r.variant === openVariant) : null;

  return (
    <section className="page page-today" aria-busy={phase.kind === "loading"}>
      <header className="page-head page-head-row">
        <div>
          <p className="page-date">{fmtDateLong(dateIso)}</p>
          <h1 className="page-title">Heute</h1>
        </div>
        <button type="button" className="icon-btn" onClick={() => setCostsOpen(true)} aria-label="Kosten anzeigen" title="Kosten">
          <Wallet aria-hidden="true" />
        </button>
      </header>

      <div className="today-main">

      {phase.kind === "loading" && (
        <div className="card skeleton" aria-hidden="true">
          <div className="skeleton-line w40" />
          <div className="skeleton-line w70" />
          <div className="skeleton-line w55" />
        </div>
      )}

      {phase.kind === "running" && <RunProgress step={phase.step} detail={phase.detail} log={phase.log} connection={phase.connection} />}

      {phase.kind === "failed" && (
        <Notice
          kind="error"
          title={phase.error.title}
          action={
            phase.retry === "start"
              ? { label: starting ? "Wird gestartet …" : "Neuen Lauf starten", onClick: () => void start(), busy: starting }
              : { label: "Nochmals versuchen", onClick: () => void load() }
          }
        >
          <p>{phase.error.hint}</p>
          {phase.runId && <p className="muted">Lauf {phase.runId}</p>}
        </Notice>
      )}

      {day && (
        <>
          <TrainingList activities={day.context.activities} source={day.source} />
          <DayGauge day={day} />
        </>
      )}

      {phase.kind === "idle" && (
        <div className="cta">
          <button type="button" className="btn btn-primary" onClick={() => void start()} disabled={starting}>
            {starting ? "Wird gestartet …" : "Vorschläge erstellen"}
          </button>
          <p className="cta-note">Zwei Modellaufrufe und Preisabfragen bei Migros, Denner und Coop. Dauert etwa eine Minute.</p>
        </div>
      )}


      </div>

      {run && (
        <div className="today-side">
          <Variants run={run} onOpen={setOpenVariant} />
        </div>
      )}

      {costsOpen && <CostsSheet onClose={() => setCostsOpen(false)} />}

      {run && openRecipe && (
        <RecipeSheet
          run={run}
          recipe={openRecipe}
          onClose={() => setOpenVariant(null)}
          onChosen={(variant) => {
            setOpenVariant(null);
            setPhase({ kind: "done", run: { ...run, chosen_variant: variant } });
            onChosen?.(variant);
          }}
        />
      )}
    </section>
  );
}

/** Detailtext ohne den Stufennamen, den die Pipeline voranstellt („Preise suchen (swissgroceries)“ → „swissgroceries“). */
function detailSuffix(label: string, detail: string): string {
  const rest = detail.startsWith(label) ? detail.slice(label.length).trim() : detail.trim();
  return rest.replace(/^\((.*)\)$/, "$1");
}

function RunProgress({ step, detail, log, connection }: { step: Step | null; detail: string | null; log: string | null; connection: "live" | "reconnecting" }) {
  const order: Step[] = ["collect", "plan", "retrieve", "execute", "compute"];
  const idx = step ? order.indexOf(step) : -1;
  return (
    <section className="card progress" aria-live="polite" aria-label="Lauf läuft">
      <h2 className="card-title">Vorschläge werden erstellt</h2>
      <ol className="steps">
        {order.map((s, i) => {
          const status = i < idx ? "done" : i === idx ? "active" : "todo";
          return (
            <li key={s} className={`step step-${status}`}>
              <span className="step-dot" aria-hidden="true" />
              <span className="step-label">
                {STEP_LABELS[s]}
                {status === "active" && detail && detailSuffix(STEP_LABELS[s], detail) && <span className="step-detail"> · {detailSuffix(STEP_LABELS[s], detail)}</span>}
              </span>
              <span className="step-state">{status === "done" ? "fertig" : status === "active" ? "läuft …" : ""}</span>
            </li>
          );
        })}
      </ol>
      {log && <p className="progress-log">{log}</p>}
      <p className="progress-foot">
        {connection === "reconnecting" ? "Verbindung unterbrochen – der Lauf läuft auf dem Mac weiter, die App verbindet neu." : "Du kannst die App schliessen; der Lauf läuft auf dem Mac weiter."}
      </p>
    </section>
  );
}

function Variants({ run, onOpen }: { run: RunResult; onOpen: (v: Variant) => void }) {
  const target = run.day?.dinner_target ?? {};
  const general = run.warnings.filter((w) => !/^(budget|schnell|aufwendig): /.test(w));
  return (
    <>
      <h2 className="section-title">Drei Varianten fürs Abendessen</h2>
      <div className="variants">
        {run.recipes.map((r) => (
          <VariantCard
            key={r.variant}
            recipe={r}
            shopping={run.shopping[r.variant]}
            target={target}
            warnings={warningsFor(r.variant, run.warnings)}
            chosen={run.chosen_variant === r.variant}
            onOpen={onOpen}
          />
        ))}
      </div>
      {general.length > 0 && (
        <Notice title="Hinweise zum Lauf">
          <ul className="plain-list">
            {general.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Notice>
      )}
      <p className="run-meta">
        Lauf {run.run_id} · {fmtInt(run.queries)} Abfragen
        {run.usage && ` · ${run.usage.calls} Modellaufrufe · ${fmtChf(run.usage.total_cost_usd)} USD`}
        {run.mock && " · Mock-Preise"}
        {run.dry_run && " · Dry-Run"}
      </p>
    </>
  );
}
