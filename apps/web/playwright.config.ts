import { defineConfig, devices } from "@playwright/test";

const webPort = 3100;
const apiPort = 8100;
const webOrigin = `http://127.0.0.1:${webPort}`;
const apiOrigin = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  use: {
    baseURL: webOrigin,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      name: "api",
      command:
        `./.venv/bin/python -m alembic upgrade head && ` +
        `./.venv/bin/python -m uvicorn app.main:app ` +
        `--host 127.0.0.1 --port ${apiPort} --log-level warning`,
      cwd: "../api",
      env: {
        PYTHONPATH: ".",
        APP_ENVIRONMENT: "development",
        DATABASE_URL: "sqlite:///./storyforge-e2e.db",
        WEB_ORIGIN: webOrigin,
        STORY_PROVIDER: "stub",
        SAFETY_PROVIDER: "stub",
        IMAGE_GEN_PROVIDER: "stub",
        TTS_PROVIDER: "stub",
        STORAGE_PROVIDER: "local",
        PAID_TTS_ENABLED: "false",
        RATE_LIMIT_ENABLED: "false",
        ASSET_CLEANUP_WORKER_ENABLED: "false",
        STORY_GENERATION_RECOVERY_ENABLED: "false",
        JWT_SECRET_KEY: "e2e-only-secret-not-for-production",
      },
      url: `${apiOrigin}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
    {
      name: "web",
      command:
        `npm run build && ` +
        `npm run start -- --hostname 127.0.0.1 --port ${webPort}`,
      env: { BACKEND_ORIGIN: apiOrigin },
      url: webOrigin,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
