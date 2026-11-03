import { expect, test, type Page } from "@playwright/test";

import { datacenterSummary, guestSummary, nodeSummary, tree } from "../src/test/fixtures";

const summaries: Record<string, unknown> = {
  "datacenter/home": datacenterSummary,
  "node/home:pve1": nodeSummary,
  "qemu/home:101": guestSummary,
};

/** Answer the UI façade from fixtures; collect CSP violations and page errors. */
async function fixtureLab(page: Page): Promise<string[]> {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  await page.route("**/api/ui/tree", (route) => route.fulfill({ json: tree }));
  await page.route("**/api/ui/objects/*/*/summary", (route) => {
    const [, , , , type = "", id = ""] = new URL(route.request().url()).pathname.split("/");
    const body = summaries[`${type}/${decodeURIComponent(id)}`];
    return body
      ? route.fulfill({ json: body })
      : route.fulfill({ status: 404, json: { detail: "not in the fixture lab" } });
  });
  return problems;
}

test("the shell loads under the harness CSP and navigates the tree", async ({ page }) => {
  const problems = await fixtureLab(page);
  const response = await page.goto("/");
  expect(response?.headers()["content-security-policy"]).toContain("script-src 'self'");

  const nav = page.getByRole("navigation", { name: "Lab" });
  await expect(nav.getByRole("link", { name: /home/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: /web-01/ })).toBeVisible();
  await expect(nav.getByText("Storage")).toBeVisible();

  await nav.getByRole("link", { name: /^pve1/ }).click();
  await expect(page).toHaveURL(/\/objects\/node\/home%3Apve1/);
  await expect(page.getByRole("heading", { level: 1, name: "pve1" })).toBeVisible();
  await expect(page.getByText("8.0 %")).toBeVisible();
  await expect(page.getByRole("table", { name: "Properties" })).toContainText("AMD Ryzen 9");

  await page.getByRole("tab", { name: "Tasks" }).click();
  await expect(page).toHaveURL(/tab=tasks/);
  await expect(page.getByText(/No task history yet/)).toBeVisible();

  expect(problems).toEqual([]);
});

test("a client route survives a reload", async ({ page }) => {
  const problems = await fixtureLab(page);
  await page.goto("/objects/datacenter/home");
  await expect(page.getByRole("list", { name: "Members" })).toContainText("pve2");
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "home" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("⌘K opens the palette and jumps to a guest", async ({ page }) => {
  const problems = await fixtureLab(page);
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Lab" }).getByText("web-01")).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog", { name: "Search the lab" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("combobox").fill("web-01");
  await expect(dialog.getByRole("option", { name: "101 web-01 · Tasks" })).toBeVisible();
  await dialog.getByRole("option", { name: "101 web-01", exact: true }).click();
  await expect(page).toHaveURL(/\/objects\/qemu\/home%3A101/);
  await expect(page.getByRole("table", { name: "Properties" })).toContainText("[MASKED]");
  expect(problems).toEqual([]);
});

test("the theme switches between light and dark", async ({ page }) => {
  await fixtureLab(page);
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("the server answers 401 without a token and the UI asks for one", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("Owner token").first()).toBeVisible();
});

test("screenshot", async ({ page }) => {
  const path = process.env.HH_E2E_SCREENSHOT;
  test.skip(!path, "set HH_E2E_SCREENSHOT to save one");
  await fixtureLab(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/objects/node/home:pve1");
  await expect(page.getByText("8.0 %")).toBeVisible();
  await page.screenshot({ path: path ?? "", fullPage: true });
});
