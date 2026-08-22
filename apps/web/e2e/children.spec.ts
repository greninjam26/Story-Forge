import { expect, test } from "@playwright/test";
import { registerParent } from "./helpers";

test("parent can create a child profile", async ({ page }) => {
  await registerParent(page);
  await expect(page).toHaveURL(/\/children$/);

  await page
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("Maya");
  await page.getByRole("spinbutton", { name: "Age" }).fill("7");
  await page
    .getByRole("textbox", { name: /^Interests/ })
    .fill("dinosaurs and space");
  await page.getByRole("combobox").selectOption("fr");
  await page.getByRole("button", { name: "Add" }).click();

  const child = page.getByRole("listitem").filter({ hasText: "Maya" });
  await expect(child).toContainText("7 yo");
  await expect(child).toContainText("dinosaurs and space");
  await expect(child).toContainText("French");
});
