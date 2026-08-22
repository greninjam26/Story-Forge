import { randomUUID } from "node:crypto";
import type { Page } from "@playwright/test";

type ChildProfile = {
  name: string;
  age: number;
  interests: string;
  language: "en" | "fr";
};

export async function registerParent(page: Page): Promise<void> {
  const email = `e2e-${randomUUID()}@example.com`;

  await page.goto("/auth/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("bedtime-story-123");
  await page.getByLabel("Confirm password").fill("bedtime-story-123");
  await page.getByRole("button", { name: "Sign up" }).click();
}

export async function createChild(
  page: Page,
  profile: ChildProfile,
): Promise<void> {
  await page
    .getByRole("textbox", { name: "Name", exact: true })
    .fill(profile.name);
  await page
    .getByRole("spinbutton", { name: "Age" })
    .fill(String(profile.age));
  await page
    .getByRole("textbox", { name: /^Interests/ })
    .fill(profile.interests);
  await page.getByRole("combobox").selectOption(profile.language);
  await page.getByRole("button", { name: "Add" }).click();
}
