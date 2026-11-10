// Zugriff auf die API unter /api. Keine Logik: nur fetch, Fehlerform {"error": {code, message}} und Typen.
// Netzfehler (Mac schläft, offline) werden zu NetworkError; HTTP-Fehler zu ApiError mit der ErrorInfo der API.

import type {
  Checklist,
  ChecklistItem,
  DayDTO,
  ErrorInfo,
  ErrorResponse,
  HistoryEntry,
  RunResult,
  RunStarted,
  ShopResponse,
  UsageResponse,
  Variant,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly info: ErrorInfo;

  constructor(status: number, info: ErrorInfo) {
    super(info.message);
    this.name = "ApiError";
    this.status = status;
    this.info = info;
  }
}

export class NetworkError extends Error {
  constructor(cause?: unknown) {
    super("Mac nicht erreichbar");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

/** Wandelt eine Antwort mit Fehlerstatus in eine ApiError um; unbekannte Körper bekommen einen generischen Text. */
export async function errorFromResponse(res: Response): Promise<ApiError> {
  let info: ErrorInfo = { code: "http_error", message: `Der Server hat mit Status ${res.status} geantwortet.` };
  try {
    const body = (await res.json()) as Partial<ErrorResponse>;
    if (body && body.error && typeof body.error.message === "string") info = body.error;
  } catch {
    // Kein JSON – generischer Text bleibt.
  }
  return new ApiError(res.status, info);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { Accept: "application/json", ...(init?.headers ?? {}) } });
  } catch (e) {
    throw new NetworkError(e);
  }
  if (!res.ok) throw await errorFromResponse(res);
  return (await res.json()) as T;
}

function json(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function patch(body: unknown): RequestInit {
  return { ...json(body), method: "PATCH" };
}

export const api = {
  day: () => request<DayDTO>("/api/day"),
  startRun: () => request<RunStarted>("/api/runs", { method: "POST" }),
  latestRun: () => request<RunResult>("/api/runs/latest"),
  run: (runId: string) => request<RunResult>(`/api/runs/${encodeURIComponent(runId)}`),
  shop: (runId: string, variant: Variant) => request<ShopResponse>(`/api/runs/${encodeURIComponent(runId)}/shop`, json({ variant })),
  checklist: (runId: string) => request<Checklist>(`/api/runs/${encodeURIComponent(runId)}/checklist`),
  patchChecklist: (runId: string, items: ChecklistItem[]) =>
    request<Checklist>(`/api/runs/${encodeURIComponent(runId)}/checklist`, patch({ items })),
  history: () => request<HistoryEntry[]>("/api/history"),
  patchHistory: (key: string, body: { cooked?: boolean; rating?: number }) =>
    request<HistoryEntry>(`/api/history/${encodeURIComponent(key)}`, patch(body)),
  usage: () => request<UsageResponse>("/api/usage"),
};

/** Verständliche Beschreibung eines Fehlers für die Anzeige (Titel + was man tun kann). */
export function describeError(e: unknown): { title: string; hint: string; code: string } {
  if (e instanceof NetworkError) {
    return {
      code: "network",
      title: "Mac nicht erreichbar",
      hint: "Schläft er oder ist er offline? Mac wecken, prüfen, dass «serve» läuft und Tailscale auf beiden Geräten verbunden ist.",
    };
  }
  if (e instanceof ApiError) {
    return { code: e.info.code, title: titleForCode(e.info.code), hint: e.info.message };
  }
  return { code: "unknown", title: "Unerwarteter Fehler", hint: e instanceof Error ? e.message : String(e) };
}

export function titleForCode(code: string): string {
  switch (code) {
    case "credits_exhausted":
      return "Guthaben leer";
    case "rate_limited":
      return "Modell ausgelastet";
    case "provider_unavailable":
      return "Modell-Anbieter nicht erreichbar";
    case "training_unavailable":
      return "intervals.icu nicht erreichbar";
    case "grocery_unavailable":
      return "Supermarkt-Preise nicht abrufbar";
    case "job_running":
      return "Es läuft bereits ein Lauf";
    case "incomplete":
      return "Lauf unvollständig";
    case "no_run_today":
      return "Noch kein Lauf heute";
    default:
      return "Das hat nicht geklappt";
  }
}
