import { expect, test } from "@playwright/test";

const ownerUser = {
  id: "owner-e2e",
  email: "owner@example.invalid",
  name: "E2E Owner",
  role: "Super Owner",
  status: "active",
  organization: { id: "aionex-org", name: "AIONEX", plan: "enterprise" },
  permissions: ["*"],
};

async function denyOwnerSession(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Not authenticated" }) });
  });
}

test("unauthenticated owner routes stay behind the private login gate", async ({ page }) => {
  await denyOwnerSession(page);
  await page.goto("/owner/production-runtime");
  await expect(page.getByRole("heading", { name: "Private control plane" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByText("Production Runtime", { exact: true })).toHaveCount(0);
});

test("authenticated Super Owner can render the production runtime contract", async ({ page }) => {
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ownerUser) });
  });
  await page.route("**/api/v1/owner/production-runtime", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        generated_at: new Date().toISOString(),
        completion: 100,
        public_origin: "https://vip-e.net",
        api_origin: "https://api.vip-e.net",
        targets: [
          { id: "database", name: "PostgreSQL", category: "runtime", status: "ready", readiness: 100, details: "1 ms query latency", last_checked_at: new Date().toISOString() },
          { id: "redis", name: "Redis", category: "runtime", status: "ready", readiness: 100, details: "1 ms ping latency", last_checked_at: new Date().toISOString() },
        ],
      }),
    });
  });
  await page.goto("/owner/production-runtime");
  await expect(page.getByRole("main").getByText("Production Runtime", { exact: true })).toBeVisible();
  await expect(page.getByText("Public origin: https://vip-e.net", { exact: true })).toBeVisible();
  await expect(page.getByText("API origin: https://api.vip-e.net", { exact: true })).toBeVisible();
});

test("owner login gate remains usable on a phone viewport", async ({ page }) => {
  await denyOwnerSession(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Private control plane" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});
