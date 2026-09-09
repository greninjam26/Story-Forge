import { expect, test } from "@playwright/test";
import { stubGoogleScript } from "./helpers";

test.beforeEach(async ({ context }) => {
  await stubGoogleScript(context);
});

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

test("parents can find Privacy and Terms before creating an account", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByRole("link", { name: "Privacy" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Terms" })).toBeVisible();
});

test("public legal pages return logged-out visitors to the homepage", async ({
  page,
}) => {
  for (const path of ["/privacy", "/terms"]) {
    await page.goto(path);
    await expect(page.getByRole("link", { name: "Back to home" })).toHaveAttribute(
      "href",
      "/",
    );
  }
});
