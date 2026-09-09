import { expect, test, type Locator } from "@playwright/test";
import { randomUUID } from "node:crypto";
import {
  blockExternalRequests,
  createChild,
  registerParent,
} from "./helpers";

async function contrastRatio(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    type LinearRgb = [number, number, number];

    function parseLinearRgb(color: string): LinearRgb | null {
      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 1;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Could not create color conversion context");
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      const [red, green, blue, alpha] = context.getImageData(0, 0, 1, 1).data;
      if (alpha === 0) return null;

      return [red, green, blue].map((channel) => {
        const value = channel / 255;
        return value <= 0.04045
          ? value / 12.92
          : ((value + 0.055) / 1.055) ** 2.4;
      }) as LinearRgb;
    }

    function luminance([red, green, blue]: LinearRgb): number {
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
    }

    const foreground = parseLinearRgb(getComputedStyle(element).color);
    let background: LinearRgb | null = null;
    let ancestor: Element | null = element;
    while (ancestor && !background) {
      background = parseLinearRgb(getComputedStyle(ancestor).backgroundColor);
      ancestor = ancestor.parentElement;
    }
    background ??= parseLinearRgb(getComputedStyle(document.documentElement).backgroundColor);

    if (!foreground || !background) {
      throw new Error("Could not resolve opaque foreground and background colors");
    }

    const lighter = Math.max(luminance(foreground), luminance(background));
    const darker = Math.min(luminance(foreground), luminance(background));
    return (lighter + 0.05) / (darker + 0.05);
  });
}

test("normal text keeps WCAG AA contrast in dark mode", async ({ browser }) => {
  const context = await browser.newContext({ colorScheme: "dark" });
  await blockExternalRequests(context);
  const page = await context.newPage();

  try {
    await page.goto("/auth/register");

    const loginLink = page.getByRole("link", { name: "Log in" });
    await expect(loginLink).toBeVisible();
    expect.soft(await contrastRatio(loginLink), "indigo action link").toBeGreaterThanOrEqual(4.5);

    await page.getByLabel("Email").fill("contrast@example.com");
    await page.getByLabel("Password", { exact: true }).fill("bedtime-story-123");
    await page.getByLabel("Confirm password").fill("different-password");
    await page.getByRole("button", { name: "Sign up" }).click();
    const validationError = page.getByText("Passwords do not match.");
    await expect(validationError).toBeVisible();
    expect.soft(await contrastRatio(validationError), "red validation text").toBeGreaterThanOrEqual(4.5);

    await registerParent(page);
    const secondaryText = page.getByText("No child profiles yet.");
    await expect(secondaryText).toBeVisible();
    expect.soft(await contrastRatio(secondaryText), "secondary children text").toBeGreaterThanOrEqual(4.5);

    let releaseReaderRequest!: () => void;
    const holdReaderRequest = new Promise<void>((resolve) => {
      releaseReaderRequest = resolve;
    });
    await context.route("**/reader/*/stories", async (route) => {
      await holdReaderRequest;
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    });

    await page.goto(`/reader/${randomUUID()}`);
    const readerLoading = page.getByText("Loading story…");
    await expect(readerLoading).toBeVisible();
    expect.soft(await contrastRatio(readerLoading), "reader loading text").toBeGreaterThanOrEqual(4.5);
    releaseReaderRequest();
  } finally {
    await context.close();
  }
});

test("parent can publish a generated story for a child to read", async ({
  browser,
  page,
}) => {
  const blockedParentRequests = await blockExternalRequests(page.context());
  await registerParent(page);
  await createChild(page, {
    name: "Noah",
    age: 5,
    interests: "space and building blocks",
    language: "en",
  });

  const child = page.getByRole("listitem").filter({ hasText: "Noah" });
  await child.getByRole("link", { name: "Open profile" }).click();
  await expect(
    page.getByRole("heading", { name: "Noah's storybook tonight" }),
  ).toBeVisible();
  const childId = new URL(page.url()).pathname.split("/").at(-1);
  if (!childId) throw new Error("Child dashboard URL did not include an ID");
  const readerUrl = await page
    .getByRole("link", { name: "Open child reader" })
    .getAttribute("href");
  if (!readerUrl) throw new Error("Child dashboard did not include a reader link");
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

  await page.getByRole("button", { name: "FR", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /^Aperçu parental :/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Illustration de la page 1", exact: true }),
  ).toBeVisible();
  const previewMain = await page.getByRole("main").boundingBox();
  expect(previewMain?.width).toBeGreaterThan(900);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "EN", exact: true }).click();

  await page
    .getByRole("button", { name: "Approve & publish to child" })
    .click();

  await expect(page.getByText(/^1 \/ \d+$/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve & publish to child" }),
  ).not.toBeVisible();

  const webOrigin = new URL(page.url()).origin;
  const readerContext = await browser.newContext();
  const blockedReaderRequests = await blockExternalRequests(readerContext);
  const readerPage = await readerContext.newPage();
  try {
    await readerPage.goto(`${webOrigin}/reader/${childId}`);
    expect(
      await readerPage.evaluate(() =>
        localStorage.getItem("storyforge-token"),
      ),
    ).toBeNull();
    await expect(readerPage.getByText("Story not found.")).toBeVisible();
    await expect(
      readerPage.getByRole("heading", { name: "Storybooks" }),
    ).not.toBeVisible();

    await readerPage.goto(`${webOrigin}${readerUrl}`);
    await expect(
      readerPage.getByRole("heading", { name: "Storybooks" }),
    ).toBeVisible();
    const readerListMain = await readerPage.getByRole("main").boundingBox();
    expect(readerListMain?.width).toBeGreaterThan(900);
    await readerPage
      .getByRole("link")
      .filter({ hasText: storyTitle })
      .click();

    const illustration = readerPage.getByRole("img", {
      name: storyTitle,
    });
    await expect(illustration).toBeVisible();
    const readerMain = await readerPage.getByRole("main").boundingBox();
    expect(readerMain?.width).toBeGreaterThan(900);
    await expect
      .poll(() =>
        illustration.evaluate((image) =>
          (image as HTMLImageElement).naturalWidth,
        ),
      )
      .toBeGreaterThan(0);

    const narrationUrl = await readerPage.locator("audio").getAttribute("src");
    expect(narrationUrl).toMatch(/^http:\/\/127\.0\.0\.1:8100\//);
    const narrationResponse = await readerPage.request.get(narrationUrl!);
    expect(narrationResponse.status()).toBe(200);
    expect(narrationResponse.headers()["content-type"]).toBe("audio/wav");

    await expect(readerPage.getByText(/^Page 1 of \d+$/)).toBeVisible();
    await readerPage.getByRole("button", { name: "Next page" }).click();
    await expect(readerPage.getByText(/^Page 2 of \d+$/)).toBeVisible();
    expect([
      ...blockedParentRequests,
      ...blockedReaderRequests,
    ]).toEqual([]);
  } finally {
    await readerContext.close();
  }
});
