import { expect, test, type Page } from "@playwright/test";

async function denyVipSession(page: Page) {
  for (const path of ["auth/me", "auth/refresh"]) {
    await page.route(`**/api/v1/${path}`, async (route) => {
      await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Not authenticated" }) });
    });
  }
}

test("VIP login renders the live authentication form", async ({ page }) => {
  await denyVipSession(page);
  await page.goto("/en/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await expect(page.getByLabel("Email address")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("protected Security Lab redirects an unauthenticated user to login", async ({ page }) => {
  await denyVipSession(page);
  await page.goto("/en/security-lab");
  await expect(page).toHaveURL(/\/en\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("Arabic login keeps the RTL boundary and mobile layout", async ({ page }) => {
  await denyVipSession(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ar/login");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  const layout = await page.evaluate(() => ({
    documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    bodyOverflow: document.body.scrollWidth > document.body.clientWidth + 1,
    emailFontSize: Number.parseFloat(getComputedStyle(document.querySelector<HTMLInputElement>("#login-email")!).fontSize),
    passwordFontSize: Number.parseFloat(getComputedStyle(document.querySelector<HTMLInputElement>("#login-password")!).fontSize),
  }));
  expect(layout.documentOverflow).toBe(false);
  expect(layout.bodyOverflow).toBe(false);
  expect(layout.emailFontSize).toBeGreaterThanOrEqual(16);
  expect(layout.passwordFontSize).toBeGreaterThanOrEqual(16);
});

test("VIP public mobile pages do not create root horizontal overflow", async ({ page }) => {
  await denyVipSession(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/ar/login", "/ar/forgot-password", "/ar/about", "/ar/pricing", "/en/login", "/en/forgot-password", "/en/about", "/en/pricing"]) {
    await page.goto(path);
    const layout = await page.evaluate(() => ({
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
    }));
    expect(layout.documentScrollWidth, path).toBeLessThanOrEqual(layout.documentWidth + 1);
    expect(layout.bodyScrollWidth, path).toBeLessThanOrEqual(layout.bodyWidth + 1);
  }
});

async function allowVipSession(page: Page) {
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "user-campaign-test",
        email: "campaign@example.invalid",
        name: "Campaign User",
        role: "User",
        status: "active",
        permissions: [],
        organization: { id: "org-campaign-test", name: "Campaign Test", plan: "pro" },
      }),
    });
  });
}

test("campaign navigation stays hidden until an advertising account is ready", async ({ page }) => {
  await allowVipSession(page);
  await page.route("**/api/v1/growth-social/paid-campaigns/readiness", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ads_manage_allowed: false,
        social_accounts_allowed: false,
        linked_ad_accounts: [],
        campaigns_visible: false,
        reason: "ads-manage-not-entitled",
        live_provider_mutation_allowed: false,
        automatic_execution_allowed: false,
        objectives: { traffic: "live-meta-ready", sales: "analysis-only", leads: "analysis-only", awareness: "analysis-only" },
      }),
    });
  });
  await page.goto("/en/dashboard");
  await expect(page.getByRole("link", { name: "Campaigns" })).toHaveCount(0);
  await page.goto("/en/campaigns");
  await expect(page).toHaveURL(/\/en\/dashboard$/);
});

test("campaign form derives provider and currency from the linked advertising account", async ({ page }) => {
  await allowVipSession(page);
  await page.route("**/api/v1/growth-social/paid-campaigns/readiness", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ads_manage_allowed: true,
        social_accounts_allowed: true,
        linked_ad_accounts: [{ id: "ad-account-1", provider: "facebook", display_name: "Meta Ads UAE", currency: "EUR", live_objectives: ["traffic"] }],
        campaigns_visible: true,
        reason: "ready",
        live_provider_mutation_allowed: false,
        automatic_execution_allowed: false,
        objectives: { traffic: "live-meta-ready", sales: "analysis-only", leads: "analysis-only", awareness: "analysis-only" },
      }),
    });
  });
  await page.route("**/api/v1/growth-social/paid-campaigns", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
      return;
    }
    await route.continue();
  });
  await page.goto("/en/campaigns");
  await expect(page.locator('select:has(option[value="ad-account-1"])')).toHaveValue("ad-account-1");
  await expect(page.locator('option[value="ad-account-1"]')).toContainText("Meta Ads UAE · facebook");
  await expect(page.getByText("Advertising account currency")).toBeVisible();
  await expect(page.getByText("EUR", { exact: true })).toBeVisible();
  await expect(page.locator('option[value="USD"]')).toHaveCount(0);
  await expect(page.locator('option[value="traffic"]')).toContainText("Meta live-path ready");
  await expect(page.locator('option[value="sales"]')).toContainText("Analysis only");
});
