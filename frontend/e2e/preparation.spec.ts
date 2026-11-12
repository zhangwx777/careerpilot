import { expect, test } from "@playwright/test";

let errors: string[] = [];

test.beforeEach(async ({ page, request }) => {
  errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => { if (response.status() >= 500) errors.push(`${response.status()} ${response.url()}`); });
  expect((await request.post("/__test/reset")).ok()).toBe(true);
});
test.afterEach(() => expect(errors).toEqual([]));

test("recommendations explain the next actions and refresh after completion", async ({ page, request }) => {
  await page.goto("/");
  const recommendations = page.getByRole("region", { name: "建议先做" });
  await expect(recommendations.getByRole("heading", { name: "建议先做" })).toBeVisible();
  await expect(recommendations.getByRole("link")).toHaveCount(2);
  const before = await (await request.get("/api/dashboard")).json();
  const first = before.recommendations[0];
  await expect(recommendations).toContainText(first.reason.label);
  expect((await request.patch(`/api/timeline/${first.timeline_node_id}/status`, { data: { status: "已完成" } })).ok()).toBe(true);
  await page.reload();
  await expect(recommendations.getByRole("link")).toHaveCount(1);
  await expect(recommendations.locator(`a[href='/timeline?focus=${first.timeline_node_id}']`)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "全部待办", exact: true })).toBeVisible();
});

for (const width of [1440, 1080, 390]) test(`practice feedback is reused by the same position only after selecting new actions at ${width}px`, async ({ page, request }) => {
  await page.setViewportSize({ width, height: 920 });
  const fixture = await (await request.post("/__test/preparation")).json();
  const sessionResponse = await request.post("/api/planner-sessions", { data: { application_id: fixture.original_application_id } });
  expect(sessionResponse.ok()).toBe(true);
  const session = await sessionResponse.json();
  expect((await request.post(`/api/planner-sessions/${session.id}/materialize-actions`, { data: { action_indexes: [0] } })).ok()).toBe(true);
  const tasks = await (await request.get(`/api/preparation-tasks?planner_session_id=${session.id}`)).json();
  await page.goto(`/practice/${tasks.items[0].id}`);
  await page.getByRole("button", { name: "生成参考答案", exact: true }).click();
  await page.getByRole("textbox", { name: "写下自己的回答" }).fill("缓存能减少回源，但还没有解释边界。");
  await page.getByRole("button", { name: "提交自答并完成", exact: true }).click();
  await expect(page.getByText("已完成这次自答练习", { exact: true })).toBeVisible();
  expect(await page.evaluate((key) => localStorage.getItem(key), `careerpilot:practice-answer:${tasks.items[0].id}`)).toBeNull();
  await page.goto("/planner");
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const history = page.getByRole("region", { name: "岗位准备复盘" });
  await expect(history.getByText("未解释失效与回源的边界", { exact: true })).toBeVisible();
  await expect(history.getByText("建议继续巩固", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `../build/plan-execution/stage2-review-${width}.png`, fullPage: true });
  await page.getByRole("button", { name: "开始备战分析", exact: true }).click();
  await expect(page.getByText("补练缓存失效与回源边界", { exact: true })).toBeVisible();
  const used = page.getByRole("region", { name: "本次使用的练习反馈" });
  await used.getByText(/查看.*点评来源/).click();
  await used.locator("details details > summary").first().click();
  await expect(used.getByText("缓存能减少回源，但还没有解释边界。", { exact: true })).toBeVisible();
  expect((await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}`)).json()).total).toBe(0);
  await page.getByRole("checkbox", { name: "选择此行动" }).check();
  await page.getByRole("button", { name: /加入.*计划/ }).click();
  await expect(page.getByText("已加入", { exact: true })).toBeVisible();
  await used.locator("summary").first().click();
  await page.getByRole("heading", { name: "岗位备战结论", exact: true }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `../build/plan-execution/stage2-plan-${width}.png`, fullPage: true });
  await page.reload();
  expect((await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}`)).json()).total).toBe(1);
  expect((await request.patch(`/api/preparation-tasks/${tasks.items[0].id}/status`, { data: { status: "待处理" } })).ok()).toBe(true);
  expect((await request.post("/__test/fail-review")).ok()).toBe(true);
  await page.goto(`/practice/${tasks.items[0].id}`);
  await page.getByRole("textbox", { name: "写下自己的回答" }).fill("后续修改的回答，点评将失败。");
  await page.getByRole("button", { name: "提交自答并完成", exact: true }).click();
  await expect(page.getByText("最近一次成功点评对应的回答", { exact: true })).toBeVisible();
  await expect(page.locator(".practice-feedback")).toContainText("缓存能减少回源，但还没有解释边界。");
  await expect(page.getByRole("textbox", { name: "写下自己的回答" })).toHaveValue("后续修改的回答，点评将失败。");
  await page.reload();
  await expect(page.getByRole("textbox", { name: "写下自己的回答" })).toHaveValue("后续修改的回答，点评将失败。");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [1440, 1080, 390]) test(`practice history handles empty data, errors and retry at ${width}px`, async ({ page, request }) => {
  const fixture = await (await request.post("/__test/preparation")).json();
  await page.setViewportSize({ width, height: 920 });
  await page.goto("/planner");
  await page.route(/\/practice-history\?/, (route) => route.abort("failed"));
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const history = page.getByRole("region", { name: "岗位准备复盘" });
  await expect(history.getByRole("alert")).toBeVisible();
  await expect(history.getByText("这个岗位还没有练习记录。", { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.unroute(/\/practice-history\?/);
  await history.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(history.getByText("这个岗位还没有练习记录。", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("legacy feedback stays undated and requires an explicit position confirmation", async ({ page, request }) => {
  const fixture = await (await request.post("/__test/preparation?legacy=true")).json();
  await page.goto("/planner");
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const history = page.getByRole("region", { name: "岗位准备复盘" });
  await expect(history).toContainText("历史记录，未保留点评时间");
  const confirm = history.getByRole("button", { name: "确认已选历史计划的岗位" });
  await expect(confirm).toBeDisabled();
  await history.getByRole("checkbox").first().check();
  await confirm.click();
  await expect(history.getByRole("checkbox")).toHaveCount(0);
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.other_position_application_id));
  await expect(history).toContainText("这个岗位还没有练习记录");
});
