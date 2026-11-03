import { defineConfig, devices } from "@playwright/test";

// The smoke test runs against the built UI served by the harness itself, so the
// real cache headers and CSP apply. The UI's API calls are answered from
// fixtures by route interception: no database, no Proxmox. Set
// HH_E2E_BASE_URL to run against an already running harness (the image).
const external = process.env.HH_E2E_BASE_URL;
const port = 4173;

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: external ?? `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: external
    ? undefined
    : {
        command: "uv run --frozen homelab-harness",
        url: `http://127.0.0.1:${port}/healthz`,
        reuseExistingServer: !process.env.CI,
        env: {
          HH_ENV: "dev",
          HH_PORT: String(port),
          HH_UI_DIR: "dist",
          HH_LOG_FORMAT: "console",
        },
      },
});
