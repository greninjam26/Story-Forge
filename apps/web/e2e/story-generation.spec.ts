import { expect, test } from "@playwright/test";
import { createChild, registerParent } from "./helpers";

test("parent can generate a story for review", async ({ page }) => {
  await registerParent(page);
  await createChild(page, {
    name: "Noah",
    age: 5,
    interests: "space and building blocks",
    language: "en",
  });

  await page.getByRole("link", { name: /Noah/ }).click();
  await expect(
    page.getByRole("heading", { name: "Noah's storybook tonight" }),
  ).toBeVisible();
  await expect(page.getByText("5 free stories left")).toBeVisible();

  await page
    .getByRole("textbox", { name: "What happened today?" })
    .fill("Noah shared his blocks with a friend at school.");
  await page.getByRole("button", { name: "Generate tonight's book" }).click();

  await expect(page.getByText("Awaiting parent review")).toBeVisible();
  await expect(page.getByText("4 free stories left")).toBeVisible();
});
