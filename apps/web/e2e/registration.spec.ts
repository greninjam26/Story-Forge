import { expect, test } from "@playwright/test";

test("parent can register and reach the children dashboard", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/auth/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("bedtime-story-123");
  await page.getByLabel("Confirm password").fill("bedtime-story-123");
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page).toHaveURL(/\/children$/);
  await expect(
    page.getByRole("heading", { name: "Your children" }),
  ).toBeVisible();
});
