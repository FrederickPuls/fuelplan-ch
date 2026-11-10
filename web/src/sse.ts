// SSE-Strom eines Laufs mit Wiederaufnahme (Abweichung 2.11): `?lastEventId=` beim (Neu-)Verbinden, Endzustand schliesst
// den Strom (sonst würde EventSource nach dem Serverende endlos neu verbinden), `replayed` heisst „Lauf schon fertig,
// Ergebnis laden“ (Abweichung 2.3). Keine Logik über den Lauf selbst – nur Transport und Zustand der Verbindung.

import type { ErrorInfo, Step } from "./types";

export type RunEvent =
  | { type: "step"; step: Step; detail: string }
  | { type: "log"; text: string }
  | { type: "done"; runId: string; replayed: boolean }
  | { type: "error"; status: number | null; info: ErrorInfo; replayed: boolean }
  | { type: "incomplete"; replayed: boolean; info: ErrorInfo | null };

export const TERMINAL_EVENTS: ReadonlySet<string> = new Set(["done", "error", "incomplete"]);
const EVENT_TYPES = ["step", "log", "done", "error", "incomplete"] as const;

/** Das Wenige, das wir von EventSource brauchen – austauschbar für Tests. */
export interface SourceLike {
  addEventListener(type: string, listener: (ev: { data?: unknown; lastEventId?: string }) => void): void;
  close(): void;
}
export type SourceFactory = (url: string) => SourceLike;

const defaultFactory: SourceFactory = (url) => new EventSource(url) as unknown as SourceLike;

export function streamUrl(runId: string, lastEventId: number): string {
  const base = `/api/runs/${encodeURIComponent(runId)}/events`;
  return lastEventId > 0 ? `${base}?lastEventId=${lastEventId}` : base;
}

function asRecord(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(data);
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function errorInfo(d: Record<string, unknown>): ErrorInfo {
  return {
    code: typeof d.code === "string" ? d.code : "error",
    message: typeof d.message === "string" ? d.message : "Der Lauf ist abgebrochen.",
    detail: typeof d.detail === "string" ? d.detail : null,
    run_id: typeof d.run_id === "string" ? d.run_id : null,
  };
}

/** SSE-Event (Name + data-Zeile) → RunEvent; Unbekanntes oder kaputtes JSON → null. */
export function parseEvent(type: string, data: unknown): RunEvent | null {
  const d = asRecord(data);
  if (!d) return null;
  const replayed = d.replayed === true;
  switch (type) {
    case "step":
      return typeof d.step === "string" ? { type: "step", step: d.step as Step, detail: typeof d.detail === "string" ? d.detail : "" } : null;
    case "log":
      return typeof d.text === "string" ? { type: "log", text: d.text } : null;
    case "done":
      return { type: "done", runId: typeof d.run_id === "string" ? d.run_id : "", replayed };
    case "error":
      return { type: "error", status: typeof d.status === "number" ? d.status : null, info: errorInfo(d), replayed };
    case "incomplete":
      return { type: "incomplete", replayed, info: typeof d.message === "string" ? errorInfo(d) : null };
    default:
      return null;
  }
}

export interface RunStreamOptions {
  createSource?: SourceFactory;
  lastEventId?: number;
  /** Verbindung weg (EventSource verbindet selbst neu); zum Anzeigen und zum Nachfragen per GET. */
  onConnectionError?: () => void;
}

export class RunStream {
  readonly runId: string;
  lastEventId: number;
  private source: SourceLike | null = null;
  private finished = false;
  private readonly onEvent: (e: RunEvent) => void;
  private readonly create: SourceFactory;
  private readonly onConnectionError: (() => void) | undefined;

  constructor(runId: string, onEvent: (e: RunEvent) => void, opts: RunStreamOptions = {}) {
    this.runId = runId;
    this.onEvent = onEvent;
    this.lastEventId = opts.lastEventId ?? 0;
    this.create = opts.createSource ?? defaultFactory;
    this.onConnectionError = opts.onConnectionError;
  }

  /** true, solange noch ein Endzustand aussteht. */
  get active(): boolean {
    return !this.finished;
  }

  get connected(): boolean {
    return this.source !== null;
  }

  /** Verbinden bzw. neu verbinden ab dem letzten bekannten Event. */
  open(): void {
    if (this.finished) return;
    this.pause();
    const src = this.create(streamUrl(this.runId, this.lastEventId));
    for (const type of EVENT_TYPES) src.addEventListener(type, (ev) => this.handle(type, ev));
    src.addEventListener("error", () => this.onConnectionError?.());
    this.source = src;
  }

  /** Verbindung schliessen, Zustand behalten (App im Hintergrund); open() nimmt wieder auf. */
  pause(): void {
    this.source?.close();
    this.source = null;
  }

  /** Endgültig schliessen. */
  close(): void {
    this.finished = true;
    this.pause();
  }

  private handle(type: string, ev: { data?: unknown; lastEventId?: string }): void {
    if (this.finished) return;
    const id = Number(ev.lastEventId);
    if (Number.isFinite(id) && id > this.lastEventId) this.lastEventId = id;
    const event = parseEvent(type, ev.data);
    if (!event) return;
    if (TERMINAL_EVENTS.has(event.type)) this.close();
    this.onEvent(event);
  }
}
