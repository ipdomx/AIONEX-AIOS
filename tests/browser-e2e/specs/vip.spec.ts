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
