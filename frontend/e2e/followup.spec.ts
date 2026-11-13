import { expect, test } from "@playwright/test";

let errors: string[] = [];
// SQLite's test-only datetime driver omits the UTC suffix; PostgreSQL retains it.
const utc = (value: string) => new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`).toISOString();
test.beforeEach(async ({ page }) => {
  errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => { if (response.status() >= 500) errors.push(`${response.status()} ${response.url()}`); });
});
test.afterEach(() => expect(errors).toEqual([]));

for (const width of [1440, 1080, 390]) test(`interview follow-up applies only confirmed suggestions at ${width}px`, async ({ page, request }) => {
  const fixture = await (await request.post("/__test/followup")).json();
  await page.setViewportSize({ width, height: 920 });
  await page.goto("/planner");
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const followup = page.getByRole("region", { name: "面试持续跟进" });
  await expect(followup.getByRole("heading", { name: "面试持续跟进" })).toBeVisible();
  await followup.getByRole("combobox", { name: "目标面试" }).selectOption(String(fixture.interview_id));
  await followup.getByRole("button", { name: "创建跟进目标", exact: true }).click();
  await expect(followup.getByRole("button", { name: "检查准备情况", exact: true })).toBeVisible();
  const before = await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}&include_deferred=true`)).json();
  await followup.getByRole("button", { name: "检查准备情况", exact: true }).click();
  await expect(followup.getByRole("checkbox")).toHaveCount(3);
  const firstSuggestion = followup.locator(".followup-suggestion").first();
  await firstSuggestion.getByText("查看依据", { exact: true }).click();
  await expect(firstSuggestion).toContainText("岗位 JD");
  await expect(firstSuggestion).toContainText("合成后端岗位");
  await expect(followup.locator(".followup-suggestion").nth(1)).toContainText("原时间：");
  await expect(followup.locator(".followup-suggestion").nth(1)).toContainText("建议时间：");
  const unchanged = await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}&include_deferred=true`)).json();
  expect(unchanged.items).toEqual(before.items);
  await expect(followup.getByRole("button", { name: "审阅并应用所选建议（0）" })).toBeDisabled();
  await followup.getByRole("checkbox", { name: "选择建议 1" }).check();
  await followup.getByRole("checkbox", { name: "选择建议 2" }).check();
  await followup.getByRole("button", { name: "审阅并应用所选建议（2）" }).click();
  const dialog = page.getByRole("dialog", { name: "确认执行所选建议？" });
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `../build/plan-execution/stage3-confirm-${width}.png` });
  expect((await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}`)).json()).total).toBe(before.total);
  await dialog.getByRole("button", { name: "确认执行", exact: true }).click();
  await expect(followup.getByText("已执行的调整", { exact: true })).toBeVisible();
  await expect(followup.getByRole("checkbox", { name: "选择建议 1" })).toBeChecked();
  await expect(followup.getByRole("checkbox", { name: "选择建议 2" })).toBeChecked();
  await expect(followup.getByRole("checkbox", { name: "选择建议 3" })).not.toBeChecked();
  const after = await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}&include_deferred=true`)).json();
  expect(after.total).toBe(before.total + 1);
  expect(after.items.find((item: { id: number }) => item.id === fixture.skip_task_id).status).toBe("待处理");
  expect(after.items.find((item: { id: number }) => item.id === fixture.started_task_id).answer_payload).toEqual(before.items.find((item: { id: number }) => item.id === fixture.started_task_id).answer_payload);
  expect(utc(after.items.find((item: { id: number }) => item.id === fixture.reschedule_task_id).scheduled_at)).toBe(utc(fixture.suggested_start));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await followup.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `../build/plan-execution/stage3-followup-${width}.png`, fullPage: true });
  await page.reload();
  await expect(followup.getByText("已执行的调整", { exact: true })).toBeVisible();
});

test("stale proposals do not overwrite a task the user started", async ({ page, request }) => {
  const fixture = await (await request.post("/__test/followup")).json();
  await page.goto("/planner");
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const followup = page.getByRole("region", { name: "面试持续跟进" });
  await followup.getByRole("combobox", { name: "目标面试" }).selectOption(String(fixture.interview_id));
  await followup.getByRole("button", { name: "创建跟进目标", exact: true }).click();
  await followup.getByRole("button", { name: "检查准备情况", exact: true }).click();
  await followup.getByRole("checkbox", { name: "选择建议 2" }).check();
  expect((await request.post(`/api/preparation-tasks/${fixture.reschedule_task_id}/answer`)).ok()).toBe(true);
  await followup.getByRole("button", { name: "审阅并应用所选建议（1）" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "确认执行", exact: true }).click();
  await expect(followup.getByRole("alert")).toBeVisible();
  const task = await (await request.get(`/api/preparation-tasks/${fixture.reschedule_task_id}`)).json();
  expect(task.answer_payload.question).toBe("缓存失效时如何保证一致性？");
  expect(utc(task.scheduled_at)).not.toBe(utc(fixture.suggested_start));
});

test("a selected skipped task can be restored and finished interviews stop follow-up", async ({ page, request }) => {
  const fixture = await (await request.post("/__test/followup")).json();
  await page.goto("/planner");
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const followup = page.getByRole("region", { name: "面试持续跟进" });
  await followup.getByRole("combobox", { name: "目标面试" }).selectOption(String(fixture.interview_id));
  await followup.getByRole("button", { name: "创建跟进目标", exact: true }).click();
  await followup.getByRole("button", { name: "暂停跟进", exact: true }).click();
  await expect(followup.getByRole("button", { name: "检查准备情况", exact: true })).toBeDisabled();
  await followup.getByRole("button", { name: "恢复跟进", exact: true }).click();
  await followup.getByRole("button", { name: "检查准备情况", exact: true }).click();
  await followup.getByRole("checkbox", { name: "选择建议 3" }).check();
  await followup.getByRole("button", { name: "审阅并应用所选建议（1）" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "确认执行", exact: true }).click();
  await expect(followup.getByText("已执行的调整", { exact: true })).toBeVisible();
  expect((await (await request.get(`/api/preparation-tasks/${fixture.skip_task_id}`)).json()).status).toBe("已跳过");
  await page.goto(`/practice/${fixture.skip_task_id}`);
  await page.getByRole("button", { name: "恢复练习", exact: true }).click();
  await expect(page.getByRole("button", { name: "生成参考答案", exact: true })).toBeVisible();
  expect((await request.patch(`/api/timeline/${fixture.interview_id}/status`, { data: { status: "已完成" } })).ok()).toBe(true);
  await page.goto("/planner");
  await expect(followup.getByText("目标已结束", { exact: true })).toBeVisible();
  await expect(followup.getByRole("button", { name: "检查准备情况", exact: true })).toBeDisabled();
});

test("model failure keeps the goal and existing tasks unchanged and can be retried", async ({ page, request }) => {
  const fixture = await (await request.post("/__test/followup")).json();
  await page.goto("/planner");
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const followup = page.getByRole("region", { name: "面试持续跟进" });
  await followup.getByRole("combobox", { name: "目标面试" }).selectOption(String(fixture.interview_id));
  await followup.getByRole("button", { name: "创建跟进目标", exact: true }).click();
  const before = await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}`)).json();
  await request.post("/__test/fail-followup");
  await followup.getByRole("button", { name: "检查准备情况", exact: true }).click();
  await expect(followup.getByRole("alert")).toBeVisible();
  await expect(followup.getByRole("button", { name: "检查准备情况", exact: true })).toBeEnabled();
  expect((await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}`)).json()).items).toEqual(before.items);
  await request.post("/__test/restore-followup");
  await followup.getByRole("button", { name: "检查准备情况", exact: true }).click();
  await expect(followup.getByRole("checkbox")).toHaveCount(3);
});

test("an automatic check appears while the goal page stays open", async ({ page, request }) => {
  await page.clock.install();
  const fixture = await (await request.post("/__test/followup")).json();
  await page.goto("/planner");
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const followup = page.getByRole("region", { name: "面试持续跟进" });
  await followup.getByRole("combobox", { name: "目标面试" }).selectOption(String(fixture.interview_id));
  await followup.getByRole("button", { name: "创建跟进目标", exact: true }).click();
  await expect(followup.getByRole("button", { name: "检查准备情况", exact: true })).toBeVisible();
  await page.clock.runFor(100);
  expect((await request.post("/__test/run-followup-scheduler")).ok()).toBe(true);
  const goals = await (await request.get(`/api/followup-goals?application_id=${fixture.same_position_application_id}`)).json();
  expect(goals[0].latest_check?.status).toBe("待确认");
  await page.clock.fastForward(31000);
  await expect(followup.getByRole("checkbox")).toHaveCount(3, { timeout: 5000 });
  expect((await (await request.get(`/api/preparation-tasks?application_id=${fixture.same_position_application_id}`)).json()).total).toBe(3);
});

for (const width of [1440, 1080, 390]) test(`follow-up loading errors are honest and recoverable at ${width}px`, async ({ page, request }) => {
  const fixture = await (await request.post("/__test/followup")).json();
  await page.setViewportSize({ width, height: 920 });
  await page.goto("/planner");
  await page.route(/\/api\/followup-goals\?/, (route) => route.abort("failed"));
  await page.getByRole("combobox", { name: "目标投递" }).selectOption(String(fixture.same_position_application_id));
  const followup = page.getByRole("region", { name: "面试持续跟进" });
  await expect(followup.getByRole("alert")).toBeVisible();
  await expect(followup.getByText("没有可新建目标的待处理面试。", { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.unroute(/\/api\/followup-goals\?/);
  await followup.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(followup.getByRole("combobox", { name: "目标面试" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
