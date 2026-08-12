import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./specs",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  use: {
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "cd ../../web-dashboard/frontend && npm exec -- next start -H 127.0.0.1 -p 3100",
      url: "http://127.0.0.1:3100",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        NEXT_PUBLIC_API_URL: "/api/v1",
        NEXT_PUBLIC_USER_PORTAL_URL: "http://127.0.0.1:3200",
      },
    },
    {
      command: "cd ../../vip-frontend && npm exec -- next start -H 127.0.0.1 -p 3200",
      url: "http://127.0.0.1:3200/en",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { NEXT_PUBLIC_API_URL: "/api/v1" },
    },
  ],
  projects: [
    {
      name: "owner-chromium",
      testMatch: /owner\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:3100" },
    },
    {
      name: "vip-chromium",
      testMatch: /vip\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:3200" },
    },
  ],
});
