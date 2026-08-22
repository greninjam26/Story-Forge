import { expect, test } from "@playwright/test";
import { createChild, registerParent } from "./helpers";

test("parent can publish a generated story for a child to read", async ({
  page,
}) => {
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
  const childId = new URL(page.url()).pathname.split("/").at(-1);
  if (!childId) throw new Error("Child dashboard URL did not include an ID");
  await expect(page.getByText("5 free stories left")).toBeVisible();

  await page
    .getByRole("textbox", { name: "What happened today?" })
    .fill("Noah shared his blocks with a friend at school.");
  await page.getByRole("button", { name: "Generate tonight's book" }).click();

  await expect(page.getByText("Awaiting parent review")).toBeVisible();
  await expect(page.getByText("4 free stories left")).toBeVisible();

  const pendingStory = page
    .getByRole("link")
    .filter({ hasText: "Awaiting parent review" });
  const storyTitle = await pendingStory.locator("span").first().innerText();
  await pendingStory.click();
  await expect(
    page.getByRole("heading", { name: /^Parent preview:/ }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Approve & publish to child" })
    .click();

  await expect(page.getByText(/^1 \/ \d+$/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve & publish to child" }),
  ).not.toBeVisible();

  await page.goto(`/reader/${childId}`);
  await expect(
    page.getByRole("heading", { name: "Storybooks" }),
  ).toBeVisible();
  await page.getByRole("link").filter({ hasText: storyTitle }).click();

  await expect(page.getByText(/^Page 1 of \d+$/)).toBeVisible();
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByText(/^Page 2 of \d+$/)).toBeVisible();
});
