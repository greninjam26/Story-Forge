import { expect, test } from "@playwright/test";

test("French preference survives registration navigation and reload", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      browserErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    browserErrors.push(error.message);
  });

  await page.goto("/");

  await page.getByRole("button", { name: "FR" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");

  await page.getByRole("link", { name: "S'inscrire" }).click();
  await expect(page).toHaveURL(/\/auth\/register$/);
  await expect(
    page.getByRole("heading", { name: "Créer votre compte" }),
  ).toBeVisible();
  expect(browserErrors).toEqual([]);

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await expect(
    page.getByRole("button", { name: "FR", pressed: true }),
  ).toBeVisible();
  expect(browserErrors).toEqual([]);
});
