// Screenshots mit Playwright (nur Entwicklung). Voraussetzung: `python -m fuelplan serve --mock --dry-run` läuft auf 127.0.0.1:8000;
// den Vite-Dev-Server startet Playwright selbst (oder nutzt einen laufenden).
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./screenshots",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    deviceScaleFactor: 2,
    locale: "de-CH",
    timezoneId: "Europe/Zurich",
  },
  projects: [
    { name: "phone-light", use: { viewport: { width: 390, height: 844 }, colorScheme: "light", isMobile: true, hasTouch: true } },
    { name: "phone-dark", use: { viewport: { width: 390, height: 844 }, colorScheme: "dark", isMobile: true, hasTouch: true } },
    { name: "laptop-light", use: { viewport: { width: 1280, height: 800 }, colorScheme: "light" } },
    { name: "laptop-dark", use: { viewport: { width: 1280, height: 800 }, colorScheme: "dark" } },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
