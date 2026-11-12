import { expect, test } from "@playwright/test";

let browserErrors: string[] = [];
test.beforeEach(async ({ page, request }) => {
  browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("response", (response) => { if (response.status() >= 500) browserErrors.push(`${response.status()} ${response.url()}`); });
  expect((await request.post("/__test/reset")).ok()).toBe(true);
});
test.afterEach(() => { expect(browserErrors).toEqual([]); });

for (const width of [1440, 1080, 390]) {
  test(`historical progress is opt-in, isolated and survives reload at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 920 });
    await page.goto("/applications");
    await page.getByRole("button", { name: "检查进度", exact: true }).click();
    const results = page.getByRole("region", { name: "历史进度检查" });
    await expect(results.getByRole("checkbox")).toHaveCount(2);
    await expect(results.getByRole("checkbox").nth(0)).not.toBeChecked();
    await expect(page.getByRole("button", { name: "确认校正已选 0 条" })).toBeDisabled();
    await results.getByRole("checkbox").nth(0).check();
    await page.getByRole("button", { name: "确认校正已选 1 条" }).click();
    await expect(page.getByRole("status")).toContainText("已校正 1 条");
    const applications = await (await request.get("/api/applications")).json();
    expect(applications.items.filter((item: { status: string }) => item.status === "笔试")).toHaveLength(1);
    expect(applications.items.filter((item: { status: string }) => item.status === "已投递")).toHaveLength(1);
    await page.reload();
    await page.getByRole("button", { name: "阶段记录", exact: true }).first().click();
    await expect(page.getByText(/历史变更来源不作推断|历史校正/).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("heading", { name: "投递台账", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../build/plan-execution/progress-${width}.png`, fullPage: true });
  });
}

test("confirmed notice creates application then completion updates calendar and dashboard", async ({ page, request }) => {
  await page.goto("/smart-entry");
  await page.getByRole("textbox", { name: "招聘通知原文" }).fill("测试笔试通知");
  await page.getByRole("button", { name: "开始识别" }).click();
  await expect(page.getByRole("button", { name: "确认并写入时间线" })).toBeVisible();
  await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/application") && response.status() === 201),
    page.getByRole("button", { name: "创建本次投递" }).click(),
  ]);
  await page.getByRole("button", { name: "确认并写入时间线" }).click();
  await expect(page).toHaveURL(/\/timeline\?/);
  const applications = await (await request.get("/api/applications")).json();
  const application = applications.items.find((item: { position: { company: { name: string } } }) => item.position.company.name === "浏览器测试公司");
  expect(application.status).toBe("笔试");
  const node = page.locator(".timeline-item").filter({ hasText: "浏览器测试公司" });
  await node.getByRole("combobox", { name: "更新节点状态" }).selectOption("已完成");
  await expect(node.getByText("✓ 已完成")).toBeVisible();
  await page.getByRole("button", { name: "月历", exact: true }).click();
  await expect(page.locator(".calendar-completed")).toContainText("已完成");
  await page.reload();
  const dashboard = await (await request.get("/api/dashboard")).json();
  expect(dashboard.feed.some((item: { application_id: number }) => item.application_id === application.id)).toBe(false);
});

test("briefing preserves its snapshot while showing current and deleted states", async ({ page, request }) => {
  await request.patch("/api/timeline/1/status", { data: { status: "已完成" } });
  await page.goto("/daily-briefings");
  await expect(page.getByText("当前：已完成")).toBeVisible();
  await expect(page.getByText(/历史笔试.*临期/)).toBeVisible();
  expect((await request.delete("/api/applications/1")).status()).toBe(204);
  await page.reload();
  await expect(page.getByText("原记录已删除")).toBeVisible();
  await expect(page.getByText(/历史笔试.*临期/)).toBeVisible();
});
