import { expect, test } from "@playwright/test";

test("French preference survives registration navigation and reload", async ({
  page,
}) => {
  const hydrationErrors: string[] = [];
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      message.text().includes("Hydration failed")
    ) {
      hydrationErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    if (error.message.includes("Hydration failed")) {
      hydrationErrors.push(error.message);
    }
  });

  await page.goto("/");

  await page.getByRole("button", { name: "FR" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");

  await page.getByRole("link", { name: "S'inscrire" }).click();
  await expect(page).toHaveURL(/\/auth\/register$/);
  await expect(
    page.getByRole("heading", { name: "Créer votre compte" }),
  ).toBeVisible();
  expect(hydrationErrors).toEqual([]);

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await expect(
    page.getByRole("button", { name: "FR", pressed: true }),
  ).toBeVisible();
  expect(hydrationErrors).toEqual([]);
});
