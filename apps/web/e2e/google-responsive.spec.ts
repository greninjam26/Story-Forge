import { expect, test } from "@playwright/test";

test("configured Google sign-in fits the narrow auth card", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 800 });
  await page.route("https://accounts.google.com/gsi/client", async (route) => {
    await route.fulfill({
      contentType: "application/javascript",
      body: `
        window.google = {
          accounts: {
            id: {
              initialize: function () {},
              renderButton: function (element, options) {
                var button = document.createElement("button");
                button.textContent = "Continue with Google";
                button.style.width = options.width + "px";
                button.style.height = "40px";
                button.style.flexShrink = "0";
                element.appendChild(button);
              }
            }
          }
        };
      `,
    });
  });

  await page.goto("/auth/register");

  const googleButton = page.getByRole("button", { name: "Continue with Google" });
  await expect(googleButton).toBeVisible();
  await page.setViewportSize({ width: 320, height: 800 });
  await expect
    .poll(() =>
      googleButton.evaluate((button) => {
        const container = button.parentElement;
        return Boolean(
          container &&
            button.getBoundingClientRect().width <=
              container.getBoundingClientRect().width,
        );
      }),
    )
    .toBe(true);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});
