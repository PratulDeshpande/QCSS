import { expect, test } from "@playwright/test";

// The plan's core journeys, each against the live bridge and embedded chassis.

test("Atlas shows the architecture and follows a real job through the pipeline", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "The virtual lab, layer by layer" })).toBeVisible();
  await expect(page.getByText("Shot executor").first()).toBeVisible();
  await page.getByText("Readout (seam 4)").first().click();
  await expect(page.getByRole("button", { name: "Open view →" })).toBeVisible();
  await page.getByRole("button", { name: "▶ Follow a job" }).click();
  await expect(page.getByText(/point\(s\), tier/)).toBeVisible();
  await expect(page.getByText(/chunk\(s\) of up to 1024 shots/)).toBeVisible();
  await page.screenshot({ path: "test-results/atlas-1440.png", fullPage: true });
});

test("Config Studio explains a device change and its apply mode", async ({ page }) => {
  await page.goto("/config?layer=B");
  const yaml = page.getByLabel("device YAML");
  await expect(yaml).toHaveValue(/t1_us/);
  const text = await yaml.inputValue();
  await yaml.fill(text.replace(/t1_us: [0-9.]+/, "t1_us: 99.5"));
  const row = page.locator("tr", { hasText: "qubits[0].t1_us" });
  await expect(row).toBeVisible();
  await expect(row).toContainText("99.5");
  await expect(row).toContainText("Energy relaxation time");
  await expect(page.getByText("✓ valid")).toBeVisible();
});

test("Admin: killing a qubit changes the hidden truth", async ({ page }) => {
  await page.goto("/admin");
  await expect(page.getByText("Truth vs belief")).toBeVisible();
  await page.getByLabel("qubit").first().selectOption("1");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Kill qubit" }).click();
  await expect(page.getByRole("status").filter({ hasText: "qubit 1 killed" })).toBeVisible();
  await expect(page.locator("tr", { hasText: "q1" }).getByText("dead")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Revive" }).click();
  await expect(page.getByRole("status").filter({ hasText: "qubit 1 revived" })).toBeVisible();
});

test("Lab bench runs a Rabi over the lab link", async ({ page }) => {
  await page.goto("/lab");
  await page.getByLabel("points").fill("5");
  await page.getByLabel("shots").fill("60");
  await page.getByRole("button", { name: "▶ Submit to the lab" }).click();
  await expect(page.getByText("pi amplitude")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("COMPLETED").first()).toBeVisible();
});

test("Program view compiles, validates and runs a job in the sandbox", async ({ page }) => {
  await page.goto("/program");
  await page.getByRole("button", { name: "▶ Run in sandbox" }).click();
  await expect(page.getByText("Program timeline")).toBeVisible();
  await expect(page.getByRole("cell", { name: "acquire" })).toBeVisible();
  await page.goto("/physics");
  await expect(page.getByText("Lindblad qutrits")).toBeVisible();
});

test("no lab or admin token ever reaches the browser", async ({ page, request }) => {
  const seen: string[] = [];
  page.on("response", async (r) => { if (r.url().includes("/api/")) seen.push(await r.text().catch(() => "")); });
  await page.goto("/admin");
  await expect(page.getByText("Truth vs belief")).toBeVisible();
  const settings = await (await request.get("/api/settings")).json();
  expect(settings).not.toHaveProperty("lab_token");
  expect(settings).not.toHaveProperty("admin_token");
  expect(seen.length).toBeGreaterThan(0);
  expect(seen.join("\n")).not.toMatch(/Bearer [A-Za-z0-9_-]{20,}/);   // an actual token, not the word in explanations
});

test("narrow viewport keeps the shell usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/learn");
  await expect(page.getByRole("heading", { name: "Tours & glossary" })).toBeVisible();
  await page.getByLabel("Search all parameters").fill("latency");
  await expect(page.getByText("LatencyEntry.latency_ticks")).toBeVisible();
  await page.screenshot({ path: "test-results/learn-390.png", fullPage: true });
});

const VIEWS: [string, string][] = [
  ["/hardware", "Hardware & timing"], ["/chip", "Chip truth"], ["/signal", "Signal chain (render seam)"], ["/readout", "Readout (seam 4)"],
  ["/timing", "Feedback & timing"], ["/boards", "Board faces"], ["/whatif", "What-if lab"], ["/config?layer=A", "Config Studio"],
];

for (const [route, heading] of VIEWS) {
  test(`view ${route} renders real data without page errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(route);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(page.getByRole("status")).toHaveCount(0, { timeout: 90_000 });       // every "computing with QCSS…" settled
    await expect(page.getByRole("alert")).toHaveCount(0);
    await page.screenshot({ path: `test-results/view${route.replace(/[/?=]/g, "_")}.png`, fullPage: true });
    expect(errors).toEqual([]);
  });
}
