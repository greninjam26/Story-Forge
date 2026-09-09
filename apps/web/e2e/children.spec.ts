import { expect, test } from "@playwright/test";
import { createChild, registerParent, stubGoogleScript } from "./helpers";

test.beforeEach(async ({ context }) => {
  await stubGoogleScript(context);
});

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

test("desktop child management uses the available workspace", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await registerParent(page);

  const main = await page.getByRole("main").boundingBox();
  expect(main?.width).toBeGreaterThan(900);
});

test("each child card exposes clear open and edit actions", async ({ page }) => {
  await registerParent(page);
  await createChild(page, {
    name: "Maya",
    age: 7,
    interests: "dinosaurs and space",
    language: "en",
  });

  const child = page.getByRole("listitem").filter({ hasText: "Maya" });
  await expect(child.getByRole("link", { name: "Open profile" })).toBeVisible();
  await expect(child.getByRole("button", { name: "Edit profile" })).toBeVisible();
});

test("parent can edit a child from the child's workspace", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await registerParent(page);
  await createChild(page, {
    name: "Maya",
    age: 7,
    interests: "space",
    language: "en",
  });

  const child = page.getByRole("listitem").filter({ hasText: "Maya" });
  await child.getByRole("link", { name: "Open profile" }).click();
  await expect(page).toHaveURL(/\/children\/[^/]+$/);
  await expect(
    page.getByRole("heading", { name: "Maya's storybook tonight" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit profile" }).click();
  const nameInput = page.getByLabel("Name", { exact: true });
  await expect(nameInput).toBeInViewport();
  await nameInput.fill("Maya Rose");
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(
    page.getByRole("heading", { name: "Maya Rose's storybook tonight" }),
  ).toBeVisible();
});
