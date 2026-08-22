import { randomUUID } from "node:crypto";
import type { BrowserContext, Page } from "@playwright/test";

type ChildProfile = {
  name: string;
  age: number;
  interests: string;
  language: "en" | "fr";
};

export async function blockExternalRequests(
  context: BrowserContext,
): Promise<string[]> {
  const blockedUrls: string[] = [];
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const isLoopback =
      url.hostname === "127.0.0.1" || url.hostname === "localhost";
    const isHttp = url.protocol === "http:" || url.protocol === "https:";
    if (isHttp && !isLoopback) {
      blockedUrls.push(url.href);
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  return blockedUrls;
}

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
