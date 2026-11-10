/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Entwicklung: der Vite-Server leitet /api an die FastAPI-App weiter (python -m fuelplan serve --mock --dry-run).
// Produktion: `vite build` schreibt nach dist/, FastAPI liefert den Ordner unter / aus (ein Port, kein CORS).
// Anderes Ziel für die Weiterleitung (z. B. die Demo auf einem zweiten Port): FUELPLAN_API=http://127.0.0.1:8010
const DEFAULT_API = "http://127.0.0.1:8000";

// Farben aus src/tokens.css (hell); die Statusleiste folgt den theme-color-Metas in index.html.
const BG_LIGHT = "#F4F3EF";

export default defineConfig(({ mode }) => {
  const API = loadEnv(mode, ".", "FUELPLAN_").FUELPLAN_API ?? DEFAULT_API;
  return {
    plugins: [
      react(),
      VitePWA({
        registerType: "autoUpdate",
        injectRegister: "auto",
        includeAssets: ["icon.svg", "apple-touch-icon.png", "favicon-32.png"],
        manifest: {
          name: "FuelPlan",
          short_name: "FuelPlan",
          description: "Training von heute, Abendessen mit echten Preisen von Migros, Denner und Coop.",
          lang: "de-CH",
          start_url: "/",
          scope: "/",
          display: "standalone",
          orientation: "portrait",
          background_color: BG_LIGHT,
          theme_color: BG_LIGHT,
          icons: [
            { src: "icon-192.png", sizes: "192x192", type: "image/png" },
            { src: "icon-512.png", sizes: "512x512", type: "image/png" },
            { src: "icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
          ],
        },
        workbox: {
          // Nur die App-Hülle vorab cachen; /api geht immer ans Netz (kein runtimeCaching, keine Navigations-Rückfallseite für /api).
          globPatterns: ["**/*.{js,css,html,svg,png,webmanifest}"],
          navigateFallback: "index.html",
          navigateFallbackDenylist: [/^\/api\//],
          runtimeCaching: [],
          cleanupOutdatedCaches: true,
          clientsClaim: true,
          skipWaiting: true,
        },
        devOptions: { enabled: false },
      }),
    ],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: API, changeOrigin: false },
      },
    },
    build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
    test: {
      environment: "node",
      include: ["src/**/*.test.ts", "scripts/**/*.test.mjs"],
    },
  };
});
