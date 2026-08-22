import { expect, test } from "@playwright/test";

test("parent can open both authentication entry points from the homepage", async ({
  page,
}) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: "Story Forge" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/auth\/login$/);
  await expect(
    page.getByRole("heading", { name: "Log in" }),
  ).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: "Sign up" }).click();
  await expect(page).toHaveURL(/\/auth\/register$/);
  await expect(
    page.getByRole("heading", { name: "Create your account" }),
  ).toBeVisible();
});
