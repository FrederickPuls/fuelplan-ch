// SSE-Wiederaufnahme: URL mit ?lastEventId=, Zähler folgt den Event-IDs, Endzustand schliesst, replayed wird durchgereicht.
import { describe, expect, it } from "vitest";
import { parseEvent, RunStream, streamUrl, type RunEvent, type SourceLike } from "./sse";

class FakeSource implements SourceLike {
  static opened: FakeSource[] = [];
  listeners = new Map<string, ((ev: { data?: unknown; lastEventId?: string }) => void)[]>();
  closed = false;
  constructor(readonly url: string) {
    FakeSource.opened.push(this);
  }
  addEventListener(type: string, listener: (ev: { data?: unknown; lastEventId?: string }) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, id: number | null, data: unknown) {
    for (const l of this.listeners.get(type) ?? []) l({ data: typeof data === "string" ? data : JSON.stringify(data), lastEventId: id == null ? "" : String(id) });
  }
}

function setup(lastEventId = 0) {
  FakeSource.opened = [];
  const events: RunEvent[] = [];
  let errors = 0;
  const stream = new RunStream("2026-11-07_1706", (e) => events.push(e), {
    createSource: (url) => new FakeSource(url),
    lastEventId,
    onConnectionError: () => {
      errors += 1;
    },
  });
  return { stream, events, errors: () => errors, source: () => FakeSource.opened[FakeSource.opened.length - 1]! };
}

describe("streamUrl", () => {
  it("hängt lastEventId nur an, wenn schon Events da waren", () => {
    expect(streamUrl("2026-11-07_1706", 0)).toBe("/api/runs/2026-11-07_1706/events");
    expect(streamUrl("2026-11-07_1706", 4)).toBe("/api/runs/2026-11-07_1706/events?lastEventId=4");
  });
});

describe("parseEvent", () => {
  it("liest step, log, done, error und incomplete", () => {
    expect(parseEvent("step", '{"step":"plan","detail":"Rezepte planen (dry-run)"}')).toEqual({ type: "step", step: "plan", detail: "Rezepte planen (dry-run)" });
    expect(parseEvent("log", '{"text":"Plan-Aufruf …"}')).toEqual({ type: "log", text: "Plan-Aufruf …" });
    expect(parseEvent("done", '{"run_id":"x","replayed":true}')).toEqual({ type: "done", runId: "x", replayed: true });
    const err = parseEvent("error", '{"status":402,"code":"credits_exhausted","message":"Guthaben leer.","detail":null,"run_id":null}');
    expect(err).toMatchObject({ type: "error", status: 402, replayed: false, info: { code: "credits_exhausted", message: "Guthaben leer." } });
    expect(parseEvent("incomplete", '{"run_id":"x","replayed":true}')).toEqual({ type: "incomplete", replayed: true, info: null });
  });
  it("ignoriert unbekannte Namen und kaputtes JSON", () => {
    expect(parseEvent("keepalive", "{}")).toBeNull();
    expect(parseEvent("step", "nicht json")).toBeNull();
    expect(parseEvent("step", '{"detail":"ohne step"}')).toBeNull();
  });
});

describe("RunStream", () => {
  it("verbindet ohne lastEventId und folgt den IDs", () => {
    const { stream, events, source } = setup();
    stream.open();
    expect(source().url).toBe("/api/runs/2026-11-07_1706/events");
    source().emit("step", 1, { step: "collect", detail: "Training" });
    source().emit("log", 2, { text: "…" });
    expect(stream.lastEventId).toBe(2);
    expect(events.map((e) => e.type)).toEqual(["step", "log"]);
    expect(stream.active).toBe(true);
  });

  it("nimmt nach pause() ab dem letzten Event wieder auf (?lastEventId=)", () => {
    const { stream, source } = setup();
    stream.open();
    source().emit("step", 3, { step: "retrieve", detail: "Preise suchen" });
    stream.pause(); // App in den Hintergrund
    expect(source().closed).toBe(true);
    expect(stream.connected).toBe(false);
    stream.open(); // sichtbar
    expect(source().url).toBe("/api/runs/2026-11-07_1706/events?lastEventId=3");
    expect(FakeSource.opened).toHaveLength(2);
  });

  it("startet mit bekanntem lastEventId (z. B. aus einer früheren Verbindung)", () => {
    const { stream, source } = setup(7);
    stream.open();
    expect(source().url).toContain("lastEventId=7");
  });

  it("schliesst beim Endzustand und nimmt danach nichts mehr an", () => {
    const { stream, events, source } = setup();
    stream.open();
    source().emit("done", 10, { run_id: "2026-11-07_1706" });
    expect(stream.active).toBe(false);
    expect(source().closed).toBe(true);
    source().emit("log", 11, { text: "zu spät" });
    stream.open(); // darf nichts mehr öffnen
    expect(FakeSource.opened).toHaveLength(1);
    expect(events).toEqual([{ type: "done", runId: "2026-11-07_1706", replayed: false }]);
  });

  it("reicht ein replayed-done nach Server-Neustart durch (Ergebnis dann per GET laden)", () => {
    const { stream, events, source } = setup(4);
    stream.open();
    source().emit("done", 1, { run_id: "2026-11-07_1706", replayed: true });
    expect(events[0]).toEqual({ type: "done", runId: "2026-11-07_1706", replayed: true });
    expect(stream.lastEventId).toBe(4); // kleinere Replay-ID setzt den Zähler nicht zurück
  });

  it("macht aus dem error-Event die Fehlerinfo der API", () => {
    const { stream, events, source } = setup();
    stream.open();
    source().emit("error", 5, { status: 503, code: "training_unavailable", message: "intervals.icu nicht erreichbar.", detail: "x", run_id: null });
    expect(events[0]).toMatchObject({ type: "error", status: 503, info: { code: "training_unavailable" } });
    expect(stream.active).toBe(false);
  });

  it("meldet Verbindungsfehler, ohne den Strom zu beenden", () => {
    const { stream, errors, source } = setup();
    stream.open();
    source().emit("error", null, "nicht json");
    expect(errors()).toBe(1);
    expect(stream.active).toBe(true);
  });

  it("verträgt Events ohne ID (Keepalive-ähnlich) und zählt nicht zurück", () => {
    const { stream, source } = setup();
    stream.open();
    source().emit("step", 6, { step: "execute", detail: "" });
    source().emit("log", null, { text: "ohne id" });
    expect(stream.lastEventId).toBe(6);
  });
});
