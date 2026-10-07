async (page) => {
  const origin = "http://127.0.0.1:4179";
  const applications = Array.from({ length: 205 }, (_, i) => ({ id: i + 1, status: "已投递", position: { id: i + 1, title: `岗位${i + 1}`, jd_text: "测试 JD", company: { id: i + 1, name: `公司${i + 1}` } } }));
  const answer = { question: "测试题", core_answer: "核心答案", personalized_answer: "定制回答", follow_ups: [] };
  const task = (id) => ({ id, planner_session_id: id, application_id: id, title: `练习${id}`, action_index: 0, category: "八股", priority: 1, status: "待处理", practice_status: "idle", practice_error: null, source_ids: [], answer_payload: answer, user_answer: null, feedback_payload: null, deferred_until: null });
  const session = (id) => ({ id, application_id: id, application: applications[id - 1], status: "已完成", draft_payload: { summary: "测试分析", strengths: [], gaps: [], actions: [{ title: `候选${id}`, detail: "测试", category: "八股", priority: 1, source_ids: [] }] } });
  let delayAnswer = false, delayCreate = false, delayTasks = false, tasksStarted = false;
  const requests = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let body = {};
    if (path === "/api/applications") {
      const start = (Number(url.searchParams.get("page") || 1) - 1) * 100;
      body = { items: applications.slice(start, start + 100), total: 205, page: start / 100 + 1, page_size: 100 };
    } else if (path === "/api/resume-profile") body = { resume_text: "测试简历", file_name: "test.pdf" };
    else if (path === "/api/planner-sessions" && request.method() === "GET") body = [];
    else if (path === "/api/planner-sessions" && request.method() === "POST") {
      await new Promise((r) => setTimeout(r, delayCreate ? 800 : 0));
      body = session(request.postDataJSON().application_id);
    } else if (/\/planner-sessions\/\d+/.test(path)) body = session(Number(path.split("/")[3]));
    else if (path === "/api/preparation-tasks") {
      const id = Number(url.searchParams.get("planner_session_id"));
      if (delayTasks && id === 1) { tasksStarted = true; await new Promise((r) => setTimeout(r, 900)); }
      body = { items: id === 2 ? [task(2)] : [], total: id === 2 ? 1 : 0, page: 1, page_size: 100 };
    } else if (/\/preparation-tasks\/\d+/.test(path)) {
      const id = Number(path.split("/")[3]);
      if (path.endsWith("/answer")) {
        await new Promise((r) => setTimeout(r, delayAnswer ? 900 : 0));
        body = { ...task(id), practice_status: "answer" };
      } else if (path.endsWith("/status")) {
        requests.push(request.postDataJSON());
        body = { ...task(id), ...request.postDataJSON() };
      } else body = task(id);
    } else if (path === "/api/dashboard") body = { pipeline: [], feed: [] };
    else if (path.includes("/providers")) body = [];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto(origin);
  await page.evaluate(() => localStorage.clear());
  const navigate = async (path) => {
    await page.evaluate((path) => { history.pushState({}, "", path); dispatchEvent(new PopStateEvent("popstate")); }, path);
  };
  await page.goto(`${origin}/practice/1`);
  await page.getByPlaceholder("先用自己的话回答，再提交给 AI 点评").fill("未提交的练习草稿");
  await page.reload();
  if (await page.getByPlaceholder("先用自己的话回答，再提交给 AI 点评").inputValue() !== "未提交的练习草稿") throw Error("练习草稿未恢复");
  await page.getByLabel("延期时间").fill("2026-12-01T12:00");
  await page.getByRole("button", { name: "确认延期" }).click();
  await page.getByRole("button", { name: "取消延期" }).click();
  if (!requests.some((r) => r.deferred_until === null) || !requests.some((r) => r.deferred_until?.endsWith("Z"))) throw Error("延期往返未提交带时区日期");
  // Remove the mock answer so this journey exercises an in-flight creation.
  await page.route("**/api/preparation-tasks/1", (route) => route.fulfill({ json: { ...task(1), answer_payload: null } }));
  await page.route("**/api/preparation-tasks/2", (route) => route.fulfill({ json: { ...task(2), answer_payload: null } }));
  await page.reload();
  delayAnswer = true;
  await page.getByRole("button", { name: "生成参考答案" }).click();
  await navigate("/practice/2");
  await page.getByRole("heading", { name: "练习2" }).waitFor();
  if (await page.getByRole("button", { name: "生成参考答案" }).isDisabled()) throw Error("新练习忙状态未复位");
  await page.waitForTimeout(1100);
  if (await page.getByRole("heading", { name: "练习2" }).count() !== 1) throw Error("旧练习覆盖新页面");
  await page.goto(`${origin}/planner`);
  const select = page.getByLabel("目标投递");
  await select.locator('option[value="205"]').waitFor({ state: "attached" });
  await select.selectOption("1");
  delayCreate = true;
  await page.getByRole("button", { name: "开始备战分析" }).click();
  await select.selectOption("2");
  await page.waitForTimeout(1100);
  if (!page.url().endsWith("/planner") || await select.inputValue() !== "2") throw Error("旧岗位响应覆盖新选择");
  await page.route("**/api/planner-sessions", async (route) => {
    if (route.request().method() === "POST") { await new Promise((r) => setTimeout(r, 800)); await route.fulfill({ status: 503, json: { detail: "旧岗位失败" } }); }
    else await route.fallback();
  });
  await select.selectOption("1");
  await page.getByRole("button", { name: "开始备战分析" }).click();
  await select.selectOption("2");
  await page.waitForTimeout(1100);
  if (await page.getByText("旧岗位失败").count()) throw Error("旧岗位失败污染新页面");
  await page.goto(`${origin}/planner/1`);
  await page.getByRole("checkbox").first().check();
  delayTasks = true;
  await page.getByRole("button", { name: "加入学习计划（1）" }).click();
  await page.waitForFunction(() => true);
  for (let i = 0; i < 30 && !tasksStarted; i++) await page.waitForTimeout(20);
  if (!tasksStarted) throw Error("未进入第二次请求");
  await navigate("/planner/2");
  await page.locator('a[href="/practice/2"]').waitFor();
  await page.waitForTimeout(1100);
  if (await page.locator('a[href="/practice/2"]').count() === 0) throw Error("旧行动覆盖新会话");
  return { passed: 6, journeys: ["练习草稿刷新恢复", "延期与取消", "练习切换隔离及忙状态复位", "205条投递与岗位生成隔离", "加入行动的第二次请求隔离", "旧岗位失败隔离"] };
}
