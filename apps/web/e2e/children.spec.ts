import { expect, test } from "@playwright/test";
import { createChild, registerParent } from "./helpers";

test("parent can create a child profile", async ({ page }) => {
  await registerParent(page);
  await expect(page).toHaveURL(/\/children$/);

  await createChild(page, {
    name: "Maya",
    age: 7,
    interests: "dinosaurs and space",
    language: "fr",
  });

  const child = page.getByRole("listitem").filter({ hasText: "Maya" });
  await expect(child).toContainText("7 yo");
  await expect(child).toContainText("dinosaurs and space");
  await expect(child).toContainText("French");
});
