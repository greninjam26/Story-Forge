import { expect, test } from "@playwright/test";
import { registerParent, stubGoogleScript } from "./helpers";

test.beforeEach(async ({ context }) => {
  await stubGoogleScript(context);
});

test("parent can register and reach the children dashboard", async ({ page }) => {
  await registerParent(page);

  await expect(page).toHaveURL(/\/children$/);
  await expect(
    page.getByRole("heading", { name: "Your children" }),
  ).toBeVisible();
});

test("signup discloses Privacy and Terms before account creation", async ({
  page,
}) => {
  await page.goto("/auth/register");

  const agreement = page.getByText(/By creating an account/);
  await expect(agreement).toBeVisible();
  await expect(agreement.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
    "href",
    "/privacy",
  );
  await expect(agreement.getByRole("link", { name: "Terms of Service" })).toHaveAttribute(
    "href",
    "/terms",
  );
});
