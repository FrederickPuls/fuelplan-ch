// Social-Preview-Bild für GitHub (1280×640) aus App-Icon, Name, Tagline und zwei README-Screenshots.
// Aufruf: `npm run social-preview` (nur Entwicklung, nach `npm run screenshots:readme`).
// Farben und Schrift aus src/tokens.css (hell); Signatur ist der Treibstoff-Balken der App.
// Ziel: docs/social-preview.png bzw. publish/overlay/docs/, falls vorhanden.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const overlay = join(repo, "publish", "overlay");
const docs = join(existsSync(overlay) ? overlay : repo, "docs");
const dataUri = (path, type) => `data:${type};base64,${readFileSync(path).toString("base64")}`;
const icon = dataUri(join(here, "..", "public", "icon.svg"), "image/svg+xml");
const today = dataUri(join(docs, "screenshots", "today.png"), "image/png");
const variants = dataUri(join(docs, "screenshots", "variants.png"), "image/png");

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  :root { --bg: #F4F3EF; --surface-2: #ECEAE4; --ink: #1B1A17; --ink-2: #5E5B53; --line: #DDDAD2; --fuel: #A05C00; }
  * { box-sizing: border-box; margin: 0; }
  body { width: 1280px; height: 640px; overflow: hidden; background: var(--bg); color: var(--ink);
         font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "Segoe UI", Roboto, sans-serif; }
  .copy { position: absolute; left: 88px; top: 0; bottom: 0; width: 560px; display: flex; flex-direction: column; justify-content: center; }
  .brand { display: flex; align-items: center; gap: 24px; }
  .brand img { width: 96px; height: 96px; border-radius: 22px; }
  h1 { font-family: ui-rounded, -apple-system, BlinkMacSystemFont, "SF Pro Rounded", "Helvetica Neue", sans-serif;
       font-size: 68px; line-height: 1; font-weight: 700; letter-spacing: -0.02em; }
  p.tagline { margin-top: 36px; font-size: 34px; line-height: 1.25; font-weight: 600; letter-spacing: -0.01em; }
  .bar { margin-top: 40px; width: 420px; height: 14px; border-radius: 7px; background: var(--surface-2); }
  .bar i { display: block; width: 40%; height: 100%; border-radius: 7px; background: var(--fuel); }
  p.meta { margin-top: 22px; font-size: 24px; line-height: 1.3; color: var(--ink-2); }
  .phone { position: absolute; width: 300px; border-radius: 36px; border: 1px solid var(--line); overflow: hidden;
           box-shadow: 0 24px 48px rgba(27, 26, 23, 0.14); background: var(--bg); }
  .phone img { display: block; width: 100%; }
  .phone.a { left: 700px; top: 64px; }
  .phone.b { left: 936px; top: 128px; }
</style>
</head>
<body>
  <div class="copy">
    <div class="brand"><img src="${icon}" alt=""><h1>FuelPlan CH</h1></div>
    <p class="tagline">Dinner that fits the training<br>I actually did.</p>
    <div class="bar"><i></i></div>
    <p class="meta">Real products and prices from<br>Migros, Coop and Denner</p>
  </div>
  <div class="phone a"><img src="${today}" alt=""></div>
  <div class="phone b"><img src="${variants}" alt=""></div>
</body>
</html>`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: 1 });
await page.setContent(html, { waitUntil: "load" });
const out = join(docs, "social-preview.png");
await page.screenshot({ path: out });
await browser.close();
console.log(`${out} (1280×640)`);
