// Gemeinsame Helfer für die Screenshot-Specs (nur Entwicklung).
import type { Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** Echter Lauf als Datenbeispiel (Intervall-Tag, echte Preise). */
export const SAMPLE_RUN = process.env.FUELPLAN_RUN ?? "2026-11-07_1706";

const HERE = dirname(fileURLToPath(import.meta.url));

/** ../Phase2_Screenshots/<block>/ relativ zum Repo fuelplan-ch/. */
export function outDir(block: string): string {
  const dir = join(HERE, "..", "..", "..", "Phase2_Screenshots", block);
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** Die fixe Tab-Bar würde in einer Ganzseiten-Aufnahme mitten im Bild landen (Aufnahme-Artefakt, nicht die App). */
export async function hideFixedBars(page: Page): Promise<void> {
  await page.addStyleTag({ content: ".tabbar{display:none}" });
}

/** /api/runs/latest → ein bestimmter Lauf (der Server liefert sonst immer „heute“). */
export async function routeLatestToRun(page: Page, runId = SAMPLE_RUN): Promise<void> {
  await page.route("**/api/runs/latest", (route) => route.continue({ url: route.request().url().replace(/\/api\/runs\/latest$/, `/api/runs/${runId}`) }));
}

export function errorBody(code: string, message: string, status = 503): string {
  return JSON.stringify({ error: { code, message }, status });
}

/** Antwort von GET /api/runs/{id} für einen abgebrochenen Lauf (HTTP 200, status "error", Abweichung 2.2). */
export function failedRunBody(runId: string, code: string, message: string): string {
  return JSON.stringify({ run_id: runId, status: "error", error: { code, message }, recipes: [], shopping: {}, warnings: [], queries: 0, mock: true, dry_run: true });
}

export async function shoot(page: Page, dir: string, name: string, scheme: string, width: number, opts: { full?: boolean } = {}): Promise<void> {
  const full = opts.full ?? true;
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(dir, `${name}-${scheme}-${width}-viewport.png`), fullPage: false });
  if (full) {
    await hideFixedBars(page);
    await page.screenshot({ path: join(dir, `${name}-${scheme}-${width}.png`), fullPage: true });
  }
}
