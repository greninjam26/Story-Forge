import { randomUUID } from "node:crypto";
import type { Page } from "@playwright/test";

export async function registerParent(page: Page): Promise<void> {
  const email = `e2e-${randomUUID()}@example.com`;

  await page.goto("/auth/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("bedtime-story-123");
  await page.getByLabel("Confirm password").fill("bedtime-story-123");
  await page.getByRole("button", { name: "Sign up" }).click();
}
