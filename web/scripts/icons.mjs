// Rendert public/icon.svg mit dem Playwright-Chromium in die PNG-Grössen für Manifest, iPhone (apple-touch-icon) und Favicon.
// Aufruf: `npm run icons` (nur Entwicklung; die PNGs liegen im Repo, damit der Build keinen Browser braucht).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const pub = join(here, "..", "public");
const svg = readFileSync(join(pub, "icon.svg"), "utf8");

const SIZES = [
  ["icon-192.png", 192],
  ["icon-512.png", 512],
  ["icon-maskable-512.png", 512], // gleiche Grafik: der Inhalt liegt in der sicheren Zone (Teller-Durchmesser 69 % der Kante)
  ["apple-touch-icon.png", 180],
  ["favicon-32.png", 32],
];

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
for (const [name, size] of SIZES) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<!doctype html><html><body style="margin:0;background:transparent">${svg.replace(/width="1024" height="1024"/, `width="${size}" height="${size}"`)}</body></html>`);
  await page.locator("svg").screenshot({ path: join(pub, name), omitBackground: true });
  console.log(`${name} (${size}×${size})`);
}
await browser.close();
