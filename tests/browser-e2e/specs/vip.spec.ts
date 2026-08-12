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
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});
