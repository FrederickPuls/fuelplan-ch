// Screenshots für die README: ein Durchlauf durch die App im Demo-Modus (erfundene Trainingswoche, Mock-Preise,
// gespeicherte Modellantworten). Aufruf: `npm --prefix web run screenshots:readme` (Konfiguration und Server:
// playwright.readme.config.ts). Ziel: docs/screenshots/ bzw. publish/overlay/docs/screenshots/, falls vorhanden.
import { expect, test, type Page } from "@playwright/test";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OVERLAY = join(REPO, "publish", "overlay");
const OUT = join(existsSync(OVERLAY) ? OVERLAY : REPO, "docs", "screenshots");
mkdirSync(OUT, { recursive: true });

async function shot(page: Page, name: string): Promise<void> {
  await page.waitForTimeout(600); // Übergänge abwarten
  await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: false });
}

test("README-Screenshots: Heute, Varianten, Rezept, Einkauf, Verlauf", async ({ page }) => {
  // Heute: Training, Tag-Typ und Bedarf, dann die drei Varianten
  await page.goto("/#/heute");
  await page.getByRole("button", { name: "Vorschläge erstellen" }).click();
  const variants = page.getByRole("heading", { name: "Drei Varianten fürs Abendessen" });
  await variants.waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "today");

  await variants.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 24));
  await shot(page, "variants");

  // Rezept-Sheet der Variante „schnell“
  await page.getByRole("button", { name: "Rezept und Zutaten" }).nth(1).click();
  await page.getByTestId("recipe-sheet").waitFor();
  await shot(page, "recipe");

  // „Diese Variante kochen“ → Einkaufsliste, zwei Positionen abhaken
  await page.getByRole("button", { name: "Diese Variante kochen" }).click();
  const rows = page.getByRole("checkbox");
  await rows.first().waitFor();
  for (const i of [0, 2]) {
    await rows.nth(i).click();
    await expect(rows.nth(i)).toHaveAttribute("aria-checked", "true");
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "shopping");

  // Verlauf: gekocht und bewertet
  await page.goto("/#/verlauf");
  const first = page.locator(".history-item").first();
  await first.waitFor();
  await first.getByRole("button", { name: "Ja" }).click();
  await first.getByRole("button", { name: "4 von 5" }).click();
  await expect(first.getByText("4 von 5", { exact: true })).toBeVisible();
  await shot(page, "history");
});
