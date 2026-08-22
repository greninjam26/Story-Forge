import { expect, test } from "@playwright/test";
import { registerParent } from "./helpers";

test("parent can register and reach the children dashboard", async ({ page }) => {
  await registerParent(page);

  await expect(page).toHaveURL(/\/children$/);
  await expect(
    page.getByRole("heading", { name: "Your children" }),
  ).toBeVisible();
});
