import { expect, test } from "@playwright/test";
import {
  blockExternalRequests,
  createChild,
  registerParent,
} from "./helpers";

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
    await expect(
      readerPage.getByRole("heading", { name: "Storybooks" }),
    ).toBeVisible();
    await readerPage
      .getByRole("link")
      .filter({ hasText: storyTitle })
      .click();

    const illustration = readerPage.getByRole("img", {
      name: storyTitle,
    });
    await expect(illustration).toBeVisible();
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
