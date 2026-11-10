// Block 3 (Runde 2 der Mockups): alle Screens und Zustände, 390 px und 1280 px, hell und dunkel → ../Phase2_Screenshots/block3/.
// Datenquellen: Heute aus dem echten Lauf 2026-11-07_1706 (per Route), Einkauf/Verlauf/Kosten vom laufenden
// `serve --mock --dry-run` (heutige Mock-Läufe mit gewählter Variante), Fehler und Offline per Route.
import { expect, test, type Page } from "@playwright/test";
import { errorBody, failedRunBody, outDir, routeLatestToRun, SAMPLE_RUN, shoot } from "./helpers";

const dir = outDir("block3");

/** Zielzustand einer Zeile herstellen (der Server-Zustand bleibt zwischen den Projekten erhalten). */
async function setChecked(row: ReturnType<Page["getByRole"]>, want: boolean) {
  const is = (await row.getAttribute("aria-checked")) === "true";
  if (is !== want) await row.click();
  await expect(row).toHaveAttribute("aria-checked", String(want));
}

async function noRunToday(page: Page) {
  await page.route("**/api/runs/latest", (route) => route.fulfill({ status: 404, contentType: "application/json", body: errorBody("no_run_today", "Heute gibt es noch keinen Lauf.") }));
}

test.describe("Heute", () => {
  test("Ergebnis mit drei Varianten", async ({ page, colorScheme, viewport }) => {
    await routeLatestToRun(page);
    await page.goto("/#/heute");
    await page.getByRole("heading", { name: "Drei Varianten fürs Abendessen" }).waitFor();
    await shoot(page, dir, "heute-varianten", colorScheme, viewport!.width);
  });

  test("vor dem Lauf (Trainingstag)", async ({ page, colorScheme, viewport }) => {
    await noRunToday(page);
    await page.route("**/api/day", async (route) => {
      const res = await route.fetch({ url: route.request().url().replace(/\/api\/day$/, `/api/runs/${SAMPLE_RUN}`) });
      const run = (await res.json()) as { day: unknown };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(run.day) });
    });
    await page.goto("/#/heute");
    await page.getByRole("button", { name: "Vorschläge erstellen" }).waitFor();
    await shoot(page, dir, "heute-vorher", colorScheme, viewport!.width);
  });

  test("Ruhetag (echte Tagesanalyse von heute)", async ({ page, colorScheme, viewport }) => {
    await noRunToday(page);
    await page.goto("/#/heute");
    await page.getByRole("button", { name: "Vorschläge erstellen" }).waitFor();
    await shoot(page, dir, "heute-ruhetag", colorScheme, viewport!.width);
  });

  test("Lauf läuft", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/runs/latest", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run_id: "2026-11-08_1200", status: "running", step: "retrieve", mock: true, dry_run: true, recipes: [], shopping: {}, warnings: [], queries: 0 }) }),
    );
    await page.route(/\/api\/runs\/[^/]+\/events/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          "retry: 60000\n\n" +
          'id: 1\nevent: step\ndata: {"step":"collect","detail":"Training lesen"}\n\n' +
          'id: 2\nevent: step\ndata: {"step":"plan","detail":"Rezepte planen (anthropic/claude-haiku-5.5)"}\n\n' +
          'id: 3\nevent: log\ndata: {"text":"Plan-Aufruf (anthropic/claude-haiku-5.5) …"}\n\n' +
          'id: 4\nevent: step\ndata: {"step":"retrieve","detail":"Preise suchen (swissgroceries)"}\n\n' +
          'id: 5\nevent: log\ndata: {"text":"Suche 7/19: Pouletbrust"}\n\n',
      }),
    );
    await page.route(/\/api\/runs\/[^/]+$/, (route) => {
      if (route.request().url().endsWith("/latest")) return route.fallback();
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run_id: "2026-11-08_1200", status: "running", step: "retrieve", mock: true, dry_run: true, recipes: [], shopping: {}, warnings: [], queries: 0 }) });
    });
    await page.goto("/#/heute");
    await page.getByRole("heading", { name: "Vorschläge werden erstellt" }).waitFor();
    await expect(page.getByText("Preise suchen")).toBeVisible();
    await shoot(page, dir, "heute-laeuft", colorScheme, viewport!.width);
  });

  test("Fehler: Guthaben leer", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/runs/latest", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: failedRunBody("2026-11-08_0900", "credits_exhausted", "OpenRouter-Guthaben leer oder Key-Limit erreicht. Guthaben aufladen oder Limit erhöhen, dann neu starten.") }),
    );
    await page.goto("/#/heute");
    await expect(page.getByRole("alert")).toContainText("Guthaben leer");
    await shoot(page, dir, "fehler-guthaben", colorScheme, viewport!.width);
  });

  test("Fehler: intervals.icu nicht erreichbar", async ({ page, colorScheme, viewport }) => {
    await noRunToday(page);
    await page.route("**/api/day", (route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: errorBody("training_unavailable", "Trainingsdaten nicht verfügbar: intervals.icu ist nicht erreichbar oder lehnt den Zugriff ab. Ohne Trainingsdaten gibt es keine Tagesanalyse.") }),
    );
    await page.goto("/#/heute");
    await expect(page.getByRole("alert")).toContainText("intervals.icu");
    await shoot(page, dir, "fehler-intervals", colorScheme, viewport!.width);
  });

  test("Fehler: Mac nicht erreichbar", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/**", (route) => route.abort("connectionrefused"));
    await page.goto("/#/heute");
    await expect(page.getByRole("alert")).toContainText("Mac nicht erreichbar");
    await shoot(page, dir, "fehler-mac", colorScheme, viewport!.width);
  });

  test("Rezept-Sheet", async ({ page, colorScheme, viewport }) => {
    await routeLatestToRun(page);
    await page.goto("/#/heute");
    await page.getByRole("button", { name: "Rezept und Zutaten" }).nth(1).click();
    await page.getByTestId("recipe-sheet").waitFor();
    await shoot(page, dir, "rezept-sheet", colorScheme, viewport!.width, { full: false });
  });

  test("Kosten-Sheet", async ({ page, colorScheme, viewport }) => {
    await routeLatestToRun(page);
    await page.goto("/#/heute");
    await page.getByRole("button", { name: "Kosten anzeigen" }).click();
    await page.getByTestId("costs-sheet").waitFor();
    await expect(page.getByText("Monatsbudget")).toBeVisible();
    await shoot(page, dir, "kosten-sheet", colorScheme, viewport!.width, { full: false });
  });
});

test.describe("Einkauf", () => {
  test("Liste, teilweise abgehakt (echter Mock-Lauf von heute)", async ({ page, colorScheme, viewport }) => {
    await page.goto("/#/einkauf");
    const rows = page.getByRole("checkbox");
    await rows.first().waitFor();
    const n = await rows.count();
    expect(n).toBeGreaterThan(3);
    // Zeilen 0 und 2 abgehakt, Zeile 1 nicht (auch zurücknehmen) → PATCH mit changed_at gegen den echten Server
    await setChecked(rows.nth(0), true);
    await setChecked(rows.nth(2), true);
    await setChecked(rows.nth(1), true);
    await setChecked(rows.nth(1), false);
    await page.waitForTimeout(800);
    await shoot(page, dir, "einkauf-liste", colorScheme, viewport!.width);

    // Neu laden → Zustand kommt vom Server zurück
    await page.reload();
    await rows.first().waitFor();
    await expect(rows.nth(0)).toHaveAttribute("aria-checked", "true");
    await expect(rows.nth(2)).toHaveAttribute("aria-checked", "true");
  });

  test("Offline: gespeicherte Liste, Abhaken geht weiter", async ({ page, colorScheme, viewport }) => {
    await page.goto("/#/einkauf");
    const rows = page.getByRole("checkbox");
    await rows.first().waitFor();
    await page.waitForTimeout(500);
    await setChecked(rows.nth(1), false);
    await page.waitForTimeout(500);
    // Mac weg
    await page.route("**/api/**", (route) => route.abort("connectionrefused"));
    await rows.nth(1).click();
    await expect(page.getByText("Offline – wird abgeglichen")).toBeVisible();
    await expect(rows.nth(1)).toHaveAttribute("aria-checked", "true");
    await shoot(page, dir, "einkauf-offline", colorScheme, viewport!.width);
    // Neu laden ohne Server: Liste kommt aus dem Speicher
    await page.reload();
    await expect(page.getByText("Offline – wird abgeglichen")).toBeVisible();
    await expect(rows.nth(1)).toHaveAttribute("aria-checked", "true");
    // Mac wieder da → Abgleich
    await page.unroute("**/api/**");
    await page.getByRole("button", { name: "Jetzt abgleichen" }).click();
    await expect(page.getByText("Offline – wird abgeglichen")).toBeHidden();
    await expect(rows.nth(1)).toHaveAttribute("aria-checked", "true");
  });

  test("leer", async ({ page, colorScheme, viewport }) => {
    await noRunToday(page);
    await page.goto("/#/einkauf");
    await page.getByText("Noch keine Variante gewählt").waitFor();
    await shoot(page, dir, "einkauf-leer", colorScheme, viewport!.width, { full: false });
  });
});

test.describe("Verlauf", () => {
  test("Einträge mit Gekocht und Bewertung", async ({ page, colorScheme, viewport }) => {
    await page.goto("/#/verlauf");
    const first = page.locator(".history-item").first();
    await first.waitFor();
    await first.getByRole("button", { name: "Ja" }).click();
    await first.getByRole("button", { name: "4 von 5" }).click();
    await expect(first.getByText("4 von 5", { exact: true })).toBeVisible();
    await page.waitForTimeout(500);
    await shoot(page, dir, "verlauf", colorScheme, viewport!.width);
    await first.getByRole("button", { name: /Rezept öffnen/ }).click();
    await page.getByTestId("recipe-sheet").waitFor();
    await shoot(page, dir, "verlauf-rezept", colorScheme, viewport!.width, { full: false });
  });

  test("leer", async ({ page, colorScheme, viewport }) => {
    await page.route("**/api/history", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.goto("/#/verlauf");
    await page.getByText("Noch keine Einträge").waitFor();
    await shoot(page, dir, "verlauf-leer", colorScheme, viewport!.width, { full: false });
  });
});
