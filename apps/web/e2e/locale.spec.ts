import { expect, test } from "@playwright/test";

test("French preference survives registration navigation and reload", async ({
  page,
}) => {
  await page.goto("/");

  await page.getByRole("button", { name: "FR" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");

  await page.getByRole("link", { name: "S'inscrire" }).click();
  await expect(page).toHaveURL(/\/auth\/register$/);
  await expect(
    page.getByRole("heading", { name: "Créer votre compte" }),
  ).toBeVisible();

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await expect(
    page.getByRole("button", { name: "FR", pressed: true }),
  ).toBeVisible();
});
