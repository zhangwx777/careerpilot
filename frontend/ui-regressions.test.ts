import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styles = readFileSync(new URL("./src/styles.css", import.meta.url), "utf8");
const plannerPage = readFileSync(new URL("./src/pages/PlannerPage.tsx", import.meta.url), "utf8");
const dashboardPage = readFileSync(new URL("./src/pages/DashboardPage.tsx", import.meta.url), "utf8");
const practicePage = readFileSync(new URL("./src/pages/PracticePage.tsx", import.meta.url), "utf8");
const intelPage = readFileSync(new URL("./src/pages/IntelPage.tsx", import.meta.url), "utf8");
const settingsPage = readFileSync(new URL("./src/pages/SettingsPage.tsx", import.meta.url), "utf8");
const timelinePage = readFileSync(new URL("./src/pages/TimelinePage.tsx", import.meta.url), "utf8");
const applicationsPage = readFileSync(new URL("./src/pages/ApplicationsPage.tsx", import.meta.url), "utf8");
const statusRail = readFileSync(new URL("./src/components/StatusRail.tsx", import.meta.url), "utf8");
const layout = readFileSync(new URL("./src/components/Layout.tsx", import.meta.url), "utf8");

test("intel chat has a dedicated always-visible vertical scrollbar", () => {
  const rule = styles.match(/\.intel-chat-history\s*\{([^}]*)\}/)?.[1] ?? "";
  assert.match(rule, /overflow-y:\s*scroll/);
  assert.match(rule, /scrollbar-gutter:\s*stable/);
  assert.match(rule, /height:\s*(?:min|clamp)\(/);
});

test("planner action selection stays interactive for candidate actions", () => {
  assert.doesNotMatch(plannerPage, /checked=\{selected\}\s+disabled=\{Boolean\(task\)\}/);
  assert.match(plannerPage, /planner-action-select/);
  assert.doesNotMatch(plannerPage, /setSelectedActionIndexes\(tasks\.map/);
});

test("practice owns completion and dashboard only links into it", () => {
  assert.match(plannerPage, /to=\{`\/practice\/\$\{task\.id\}`\}/);
  assert.doesNotMatch(plannerPage, /提交自答并完成/);
  assert.doesNotMatch(dashboardPage, /can_complete|今天先做|打开行动/);
  assert.match(dashboardPage, /进入练习|接下来/);
  assert.match(practicePage, /提交自答并完成/);
  assert.match(dashboardPage, /移出计划/);
  assert.doesNotMatch(dashboardPage, /item\.detail/);
});

test("dashboard keeps summary cards aligned and avoids stretched empty panels", () => {
  assert.match(styles, /\.dashboard-overview-grid\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:/s);
  assert.match(styles, /\.dashboard-metric-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,/s);
  assert.match(styles, /\.dashboard-empty\s*\{[^}]*min-height:\s*128px;/s);
  assert.match(dashboardPage, /dashboard-pipeline-card[\s\S]*dashboard-metric-grid/);
  assert.match(dashboardPage, /dashboard-next-card/);
  assert.match(dashboardPage, /dashboard-card-link/);
  assert.doesNotMatch(dashboardPage, /主要阶段|dashboard-stat-stage/);
});

test("planner is single-column and action metadata has a stable side rail", () => {
  assert.match(styles, /\.planner-grid\s*\{\s*display:\s*block;/);
  assert.match(styles, /\.planner-action-side-meta\s*\{/);
  assert.doesNotMatch(plannerPage, /分析范围/);
});

test("wide pages and upload dropzone use one visual content boundary", () => {
  assert.match(styles, /\.practice-layout\s*\{\s*width:\s*100%;\s*max-width:\s*none;/);
  assert.match(styles, /\.briefing-grid\s*\{\s*display:\s*block;/);
  assert.match(styles, /\.briefing-content section\s*\{[^}]*max-width:\s*none;/s);
  assert.match(styles, /\.intel-upload-zone\s*\{[^}]*box-sizing:\s*border-box;/s);
  assert.match(styles, /\.upload-control\s*\{[^}]*min-height:\s*92px;/s);
});

test("plan selection is an unlabeled accessible checkbox and views refresh after task changes", () => {
  assert.match(plannerPage, /aria-label="选择此行动"/);
  assert.doesNotMatch(plannerPage, /planner-check-label/);
  assert.match(plannerPage, /preparation-task-updated/);
  assert.match(plannerPage, /preparation-plan-updated/);
  assert.match(dashboardPage, /preparation-task-updated/);
  assert.match(dashboardPage, /preparation-plan-updated/);
});

test("navigation, timeline and settings keep their distinct responsibilities", () => {
  assert.match(styles, /\.app-shell\s*\{\s*height:\s*100dvh;[^}]*overflow:\s*hidden;/s);
  assert.match(styles, /\.sidebar\s*\{[^}]*overflow-y:\s*auto;/s);
  assert.match(styles, /\.workspace\s*\{[^}]*overflow-y:\s*auto;/s);
  assert.match(styles, /\.intel-tabs button\.active\s*\{[^}]*background:/s);
  assert.doesNotMatch(styles, /\.intel-tabs button\.active\s*\{[^}]*box-shadow:/s);
  assert.match(styles, /\.intel-tabs button:focus-visible/);
  assert.match(styles, /\.intel-library-filter\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(intelPage, /轮次筛选/);
  assert.match(timelinePage, /完整日程/);
  assert.match(dashboardPage, /查看完整日程/);
  assert.match(settingsPage, /settings-disclosure/);
  assert.match(settingsPage, /使用场景/);
  assert.match(settingsPage, /公开检索/);
  assert.match(layout, /求职地图/);
  assert.match(layout, /面经情报[\s\S]*备战中心[\s\S]*每日简报/);
  assert.match(styles, /\.brand div span\s*\{[^}]*white-space:\s*nowrap;/s);
});

test("application ledger presents the current node as the progression control", () => {
  assert.match(applicationsPage, /<span>投递阶段<\/span>/);
  assert.match(applicationsPage, /<StatusRail status=\{application\.status\} \/>/);
  assert.match(applicationsPage, /value=\{application\.status\}/);
  assert.match(applicationsPage, /APPLICATION_STATUSES\.map/);
  assert.doesNotMatch(applicationsPage, /下一步|推进至…/);
  assert.doesNotMatch(statusRail, /is-reached|status-label/);
});
