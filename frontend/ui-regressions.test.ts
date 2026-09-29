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
const smartEntryPage = readFileSync(new URL("./src/pages/SmartEntryPage.tsx", import.meta.url), "utf8");
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
});

test("status rail highlights reached stages and marks the current node", () => {
  // 轨道按当前状态在阶段序列中的位置高亮已达节点，并标出当前节点
  assert.match(statusRail, /indexOf\(status\)/);
  assert.match(statusRail, /is-reached/);
  assert.match(statusRail, /is-current/);
  // 终态“挂”不落在阶段轨道上，整条置灰单独标记
  assert.match(statusRail, /"挂"/);
  assert.match(statusRail, /is-rejected/);
  // 高亮样式必须真正存在于 CSS 中
  assert.match(styles, /\.status-rail\s+[^{]*\.is-reached/);
  assert.match(styles, /\.status-rail\s+[^{]*\.is-current/);
  assert.match(styles, /\.status-rail\.is-rejected/);
});

test("smart entry lets the user own the deadline instead of recomputing over it", () => {
  // 工作日推算只在截止时间为空时补建议值，绝不覆盖已填写的截止时间
  assert.doesNotMatch(smartEntryPage, /if \(timeMode === "截止窗口" && scheduledAt && deadlineWorkdays\) \{/);
  assert.match(smartEntryPage, /!endsAt/);
  // 完成时限与通知来源不再由用户手填
  assert.doesNotMatch(smartEntryPage, /完成时限/);
  assert.doesNotMatch(smartEntryPage, /邮件 \/ 短信 \/ 网页/);
  assert.doesNotMatch(smartEntryPage, /setDeadlineWorkdays\(event\.target\.value/);
  assert.doesNotMatch(smartEntryPage, /setSource\(event\.target\.value\)/);
});
