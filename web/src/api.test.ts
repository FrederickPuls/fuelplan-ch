// Fehlerformat der API: {"error": {code, message, detail?, run_id?}} → ApiError; kein JSON → generischer Text;
// Netzfehler → NetworkError mit Hinweis „Mac nicht erreichbar“.
import { describe, expect, it } from "vitest";
import { ApiError, describeError, errorFromResponse, NetworkError, titleForCode } from "./api";

function response(status: number, body: string, type = "application/json"): Response {
  return new Response(body, { status, headers: { "Content-Type": type } });
}

describe("errorFromResponse", () => {
  it("liest Code, Text und run_id aus dem API-Format", async () => {
    const e = await errorFromResponse(response(409, '{"error":{"code":"job_running","message":"Es läuft bereits ein Lauf.","run_id":"2026-11-08_0900"}}'));
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(409);
    expect(e.info.code).toBe("job_running");
    expect(e.info.run_id).toBe("2026-11-08_0900");
    expect(e.message).toBe("Es läuft bereits ein Lauf.");
  });

  it("fällt bei fremdem Körper auf einen generischen Text zurück", async () => {
    const e = await errorFromResponse(response(502, "<html>Bad Gateway</html>", "text/html"));
    expect(e.info.code).toBe("http_error");
    expect(e.info.message).toContain("502");
    const e2 = await errorFromResponse(response(500, '{"detail":"anders"}'));
    expect(e2.info.code).toBe("http_error");
  });
});

describe("describeError", () => {
  it("nennt bei Netzfehlern den Mac und was zu tun ist", () => {
    const d = describeError(new NetworkError(new TypeError("Failed to fetch")));
    expect(d.code).toBe("network");
    expect(d.title).toBe("Mac nicht erreichbar");
    expect(d.hint).toMatch(/schläft|offline/i);
    expect(d.hint).toMatch(/serve/);
  });

  it("übernimmt bei API-Fehlern den Text der API als Hinweis", () => {
    const d = describeError(new ApiError(402, { code: "credits_exhausted", message: "Guthaben aufladen, dann neu starten." }));
    expect(d.title).toBe("Guthaben leer");
    expect(d.hint).toBe("Guthaben aufladen, dann neu starten.");
  });

  it("hat Titel für alle Fehlercodes aus Phase 1", () => {
    for (const code of ["credits_exhausted", "rate_limited", "provider_unavailable", "training_unavailable", "grocery_unavailable", "job_running", "incomplete"]) {
      expect(titleForCode(code)).not.toBe("Das hat nicht geklappt");
    }
    expect(titleForCode("irgendwas")).toBe("Das hat nicht geklappt");
  });
});
