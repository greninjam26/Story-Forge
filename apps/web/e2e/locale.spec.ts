import { expect, test } from "@playwright/test";
import { stubGoogleScript } from "./helpers";

test.beforeEach(async ({ context }) => {
  await stubGoogleScript(context);
});

async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

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

  await page.getByRole("button", { name: "FR", exact: true }).click();
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

test("French public pages fit narrow mobile screens", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "FR" }).click();

  await expectNoHorizontalOverflow(page);
  await page.getByRole("link", { name: "S'inscrire" }).click();
  await expectNoHorizontalOverflow(page);
  await page.getByRole("link", { name: "Conditions d'utilisation" }).click();
  await expectNoHorizontalOverflow(page);
});
