// Block 2: vollständiger Ablauf auf „Heute“ gegen `serve --mock --dry-run`, inklusive Reload während des Laufs, plus alle
// Fehlerzustände. Der Mock-Lauf ist in unter einer Sekunde fertig; damit der Reload wirklich „im Lauf“ passiert, halten
// die Routen Status und Ereignisstrom ein paar Sekunden künstlich auf „running“ – der Start (POST), die Wiederaufnahme per
// Last-Event-ID gegen den echten Puffer, das Ergebnis und `shop` laufen gegen den echten Server.
import { expect, test } from "@playwright/test";
import { errorBody, failedRunBody, outDir, shoot } from "./helpers";

const SLOW_MS = 6000;

test("Lauf bis zur Auswahl, Reload während des Laufs", async ({ page, colorScheme, viewport }) => {
  const dir = outDir("block2");
  const width = viewport?.width ?? 0;
  let runId: string | null = null;
  let startedAt = 0;
  const slow = () => runId !== null && Date.now() - startedAt < SLOW_MS;

  await page.route("**/api/runs/latest", (route) => {
    if (!runId) return route.fulfill({ status: 404, contentType: "application/json", body: errorBody("no_run_today", "Heute gibt es noch keinen Lauf.") });
    if (slow()) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run_id: runId, status: "running", step: "retrieve", mock: true, dry_run: true, recipes: [], shopping: {}, warnings: [], queries: 0 }) });
    return route.continue({ url: route.request().url().replace(/\/api\/runs\/latest$/, `/api/runs/${runId}`) });
  });
  await page.route("**/api/runs", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as { run_id: string };
    runId = body.run_id;
    startedAt = Date.now();
    await route.fulfill({ status: res.status(), contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route(/\/api\/runs\/[^/]+\/events/, (route) => {
    if (!slow()) return route.continue();
    // zwei Stufen, dann Ende des Körpers → EventSource verbindet nach `retry` neu, mit Last-Event-ID: 2
    const body =
      "retry: 700\n\n" +
      'id: 1\nevent: step\ndata: {"step":"collect","detail":"Training lesen"}\n\n' +
      'id: 2\nevent: step\ndata: {"step":"plan","detail":"Rezepte planen (dry-run)"}\n\n';
    return route.fulfill({ status: 200, contentType: "text/event-stream", body });
  });
  await page.route(/\/api\/runs\/[^/]+$/, (route) => {
    if (route.request().url().endsWith("/api/runs/latest")) return route.fallback(); // gehört der Route oben
    if (route.request().method() !== "GET" || !slow()) return route.continue();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run_id: runId, status: "running", step: "plan", mock: true, dry_run: true, recipes: [], shopping: {}, warnings: [], queries: 0 }) });
  });

  await page.goto("/#/heute");
  await page.getByRole("button", { name: "Vorschläge erstellen" }).click();
  await page.getByRole("heading", { name: "Vorschläge werden erstellt" }).waitFor();
  await expect(page.getByText("Rezepte planen")).toBeVisible();
  await shoot(page, dir, "heute-laeuft", colorScheme, width, { full: false });

  await page.reload();
  await page.getByRole("heading", { name: "Vorschläge werden erstellt" }).waitFor();
  await page.getByRole("heading", { name: "Drei Varianten fürs Abendessen" }).waitFor({ timeout: 25_000 });
  await expect(page.getByText(/Lauf \d{4}-\d{2}-\d{2}_\d{4}/)).toBeVisible();

  await page.getByRole("button", { name: "Rezept und Zutaten" }).first().click();
  const sheet = page.getByRole("dialog");
  await sheet.waitFor();
  await expect(sheet.getByRole("heading", { name: "Zutaten", exact: false })).toBeVisible();
  await shoot(page, dir, "rezept-sheet", colorScheme, width, { full: false });

  await sheet.getByRole("button", { name: "Diese Variante kochen" }).click();
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("#/einkauf");
  await expect(page.getByText("Variante gewählt")).toBeVisible();
  await shoot(page, dir, "einkauf-platzhalter", colorScheme, width, { full: false });

  await page.goto("/#/heute");
  await expect(page.getByText("gewählt", { exact: true })).toBeVisible();
  await shoot(page, dir, "heute-gewaehlt", colorScheme, width);
});

test.describe("Fehlerzustände", () => {
  test("Guthaben leer (Lauf mit status error, HTTP 200)", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/runs/latest", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: failedRunBody("2026-11-08_0900", "credits_exhausted", "OpenRouter-Guthaben leer oder Key-Limit erreicht. Guthaben aufladen oder Limit erhöhen, dann neu starten.") }),
    );
    await page.goto("/#/heute");
    await expect(page.getByRole("alert")).toContainText("Guthaben leer");
    await expect(page.getByRole("button", { name: "Neuen Lauf starten" })).toBeVisible();
    await shoot(page, outDir("block2"), "fehler-guthaben", colorScheme, viewport?.width ?? 0);
  });

  test("intervals.icu nicht erreichbar", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/runs/latest", (route) => route.fulfill({ status: 404, contentType: "application/json", body: errorBody("no_run_today", "Heute gibt es noch keinen Lauf.") }));
    await page.route("**/api/day", (route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: errorBody("training_unavailable", "Trainingsdaten nicht verfügbar: intervals.icu ist nicht erreichbar oder lehnt den Zugriff ab. Ohne Trainingsdaten gibt es keine Tagesanalyse.") }),
    );
    await page.goto("/#/heute");
    await expect(page.getByRole("alert")).toContainText("intervals.icu nicht erreichbar");
    await shoot(page, outDir("block2"), "fehler-intervals", colorScheme, viewport?.width ?? 0);
  });

  test("swissgroceries nicht erreichbar (Lauf abgebrochen)", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/runs/latest", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: failedRunBody("2026-11-08_0905", "grocery_unavailable", "Supermarkt-Preise nicht abrufbar: swissgroceries bzw. Coop antwortet nicht (Bot-Schutz oder Dienst gestört). Später nochmals versuchen.") }),
    );
    await page.goto("/#/heute");
    await expect(page.getByRole("alert")).toContainText("Supermarkt-Preise nicht abrufbar");
    await shoot(page, outDir("block2"), "fehler-swissgroceries", colorScheme, viewport?.width ?? 0);
  });

  test("Mac nicht erreichbar", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/**", (route) => route.abort("connectionrefused"));
    await page.goto("/#/heute");
    await expect(page.getByRole("alert")).toContainText("Mac nicht erreichbar");
    await expect(page.getByRole("button", { name: "Nochmals versuchen" })).toBeVisible();
    await shoot(page, outDir("block2"), "fehler-mac", colorScheme, viewport?.width ?? 0);
  });

  test("Ruhetag (echte Tagesanalyse von heute)", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/runs/latest", (route) => route.fulfill({ status: 404, contentType: "application/json", body: errorBody("no_run_today", "Heute gibt es noch keinen Lauf.") }));
    await page.goto("/#/heute");
    await page.getByRole("button", { name: "Vorschläge erstellen" }).waitFor();
    await shoot(page, outDir("block2"), "heute-ruhetag", colorScheme, viewport?.width ?? 0);
  });
});
