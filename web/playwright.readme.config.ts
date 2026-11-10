// Screenshots für die README (nur Entwicklung): `npm --prefix web run screenshots:readme`.
// Startet alles selbst auf eigenen Ports: die Demo-API (`python -m fuelplan demo`, erfundene Trainingswoche,
// Mock-Preise, gespeicherte Modellantworten) und einen Vite-Server, der /api dorthin weiterleitet.
// Ein laufendes `serve` auf Port 8000 bleibt unberührt. Anderes Python: FUELPLAN_PYTHON=/pfad/zu/python.
import { defineConfig } from "@playwright/test";

const API_PORT = 8010;
const WEB_PORT = 5174;
const PYTHON = process.env.FUELPLAN_PYTHON ?? ".venv/bin/python";

export default defineConfig({
  testDir: "./screenshots",
  testMatch: "readme.shots.ts",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    colorScheme: "light",
    isMobile: true,
    hasTouch: true,
    locale: "de-CH",
    timezoneId: "Europe/Zurich",
  },
  webServer: [
    {
      command: `${PYTHON} -m fuelplan demo --port ${API_PORT}`,
      cwd: "..",
      env: { FUELPLAN_WEIGHT_KG: "70" }, // Beispielgewicht, unabhängig von der eigenen .env
      url: `http://127.0.0.1:${API_PORT}/api/day`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `npm run dev -- --port ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { FUELPLAN_API: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
