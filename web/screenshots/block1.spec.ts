// Block 1: Screen „Heute“ mit drei Variantenkarten, 390 px, hell und dunkel → ../Phase2_Screenshots/block1/.
// Der Server liefert immer „heute“; für den Screenshot wird /api/runs/latest auf den echten Lauf 2026-11-07_1706
// umgelenkt (Intervall-Tag, echte Preise). Die App selbst bleibt unverändert.
import { test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RUN = process.env.FUELPLAN_RUN ?? "2026-11-07_1706";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "..", "..", "Phase2_Screenshots", "block1");
mkdirSync(OUT, { recursive: true });

test.skip(({ viewport }) => (viewport?.width ?? 0) > 500, "Block 1: nur iPhone-Breite");

async function routeLatestToRun(page: Page) {
  await page.route("**/api/runs/latest", (route) =>
    route.continue({ url: route.request().url().replace(/\/api\/runs\/latest$/, `/api/runs/${RUN}`) }),
  );
}

test("Heute mit drei Varianten", async ({ page, colorScheme }) => {
  await routeLatestToRun(page);
  await page.goto("/#/heute");
  await page.getByRole("heading", { name: "Drei Varianten fürs Abendessen" }).waitFor();
  await page.waitForTimeout(600); // Balken-Animation ausklingen lassen
  await page.screenshot({ path: join(OUT, `heute-varianten-${colorScheme}-390-viewport.png`), fullPage: false });
  await hideFixedBars(page); // fixe Tab-Bar würde in der Ganzseiten-Aufnahme mitten im Bild landen (Aufnahme-Artefakt)
  await page.screenshot({ path: join(OUT, `heute-varianten-${colorScheme}-390.png`), fullPage: true });
});

async function hideFixedBars(page: Page) {
  await page.addStyleTag({ content: ".tabbar{display:none}" });
}

test("Heute vor dem Lauf", async ({ page, colorScheme }) => {
  // Kein Lauf heute → Tagesanalyse des Beispiel-Laufs plus Button
  await page.route("**/api/runs/latest", (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "no_run_today", message: "Heute gibt es noch keinen Lauf." } }) }),
  );
  await page.route("**/api/day", async (route) => {
    const res = await route.fetch({ url: route.request().url().replace(/\/api\/day$/, `/api/runs/${RUN}`) });
    const run = (await res.json()) as { day: unknown };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(run.day) });
  });
  await page.goto("/#/heute");
  await page.getByRole("button", { name: "Vorschläge erstellen" }).waitFor();
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(OUT, `heute-vorher-${colorScheme}-390-viewport.png`), fullPage: false });
  await hideFixedBars(page);
  await page.screenshot({ path: join(OUT, `heute-vorher-${colorScheme}-390.png`), fullPage: true });
});
