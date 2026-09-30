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

test("software update lives beside the brand instead of the settings page", () => {
  const badge = readFileSync(new URL("./src/components/UpdateBadge.tsx", import.meta.url), "utf8");
  assert.match(layout, /<strong>职航<\/strong>\s*<UpdateBadge \/>/);
  assert.match(badge, /useEffect\(\(\) => \{[^]*?bridge\.check\(/);
  assert.match(badge, /onProgress/);
  assert.match(badge, /window\.confirm/);
  assert.doesNotMatch(settingsPage, /软件更新|careerPilotUpdates|update-settings-card/);
});

test("intel chat history has an internal scroll region when messages exist", () => {
  const rule = styles.match(/\.intel-chat-history\s*\{([^}]*)\}/)?.[1] ?? "";
  assert.match(intelPage, /className="intel-chat-history"/);
  assert.match(rule, /overflow-y:\s*auto/);
  assert.match(rule, /scrollbar-gutter:\s*stable/);
  assert.match(rule, /min-height:\s*0/);
});

test("intel workbench uses a fixed, independently scrollable chat window", () => {
  assert.match(intelPage, /createPortal/);
  assert.match(intelPage, /aria-expanded=\{chatOpen\}/);
  assert.match(intelPage, /aria-controls="intel-chat-window"/);
  assert.match(intelPage, /role="dialog"/);
  assert.match(intelPage, /chatHistoryRef/);
  assert.match(intelPage, /scrollTop\s*=\s*[^;]*scrollHeight/);
  assert.doesNotMatch(intelPage, /<details className="intel-chat-turn"/);
  assert.match(styles, /\.intel-workbench\s*\{[^}]*grid-template-columns:\s*1fr;/s);
  assert.match(styles, /\.intel-chat-window\s*\{[^}]*position:\s*fixed;/s);
  assert.match(styles, /\.intel-chat-window\s*\{[^}]*width:\s*min\(420px,/s);
  assert.match(styles, /\.intel-chat-window\s*\{[^}]*max-height:\s*min\(680px,/s);
  assert.match(styles, /\.intel-chat-history\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto/s);
  assert.match(styles, /@media\s*\(max-width:\s*540px\)[\s\S]*?\.intel-chat-window/);
});

test("intel chat exposes answer copy, turn deletion, clear history and generation errors", () => {
  assert.match(intelPage, /navigator\.clipboard\.writeText/);
  assert.match(intelPage, /deleteChatTurn\(/);
  assert.match(intelPage, /clearChatHistory\(/);
  assert.match(intelPage, /answer\.error_message/);
  assert.match(intelPage, /复制回答/);
  assert.match(intelPage, /清空历史/);
  assert.match(styles, /\.intel-chat-copy/);
  assert.match(styles, /\.intel-chat-delete-turn/);
});

test("intel insights keep a compact round overview and move preparation focus out", () => {
  assert.match(intelPage, /<h3>轮次概览<\/h3>/);
  assert.doesNotMatch(intelPage, /<h3>准备重点<\/h3>/);
  assert.doesNotMatch(intelPage, /className="intel-preparation-list"/);
  assert.match(intelPage, /onAsk=\{[^}]*openChat/);
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

test("planner strengths and gaps keep evidence readable in distinct groups", () => {
  assert.match(plannerPage, /planner-insight-strengths/);
  assert.match(plannerPage, /planner-insight-gaps/);
  assert.match(plannerPage, /planner-insight-preview/);
  assert.match(styles, /\.planner-insight-strengths\s*\{[^}]*background:/s);
  assert.match(styles, /\.planner-insight-gaps\s*\{[^}]*background:/s);
  assert.match(styles, /-webkit-line-clamp:\s*2/);
  assert.match(styles, /\.planner-summary p\s*\{[^}]*max-width:\s*82ch/);
});

test("wide pages and the intel composer use one visual content boundary", () => {
  assert.match(styles, /\.practice-layout\s*\{\s*width:\s*100%;\s*max-width:\s*none;/);
  assert.match(styles, /\.briefing-grid\s*\{\s*display:\s*block;/);
  assert.match(styles, /\.briefing-content section\s*\{[^}]*max-width:\s*none;/s);
  assert.match(intelPage, /className="intel-composer"/);
  assert.match(styles, /\.intel-composer\s*\{[^}]*border:\s*1px solid/s);
  assert.match(styles, /\.intel-composer-actions\s*\{/);
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
  assert.doesNotMatch(intelPage, /轮次筛选|intel-library-filter/);
  assert.match(intelPage, /<Materials items=\{dossier\?\.materials \?\? \[\]\}/);
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
  assert.match(smartEntryPage, /timeMode === "固定时间" && \(/);
  assert.match(smartEntryPage, /scheduled_at: timeMode === "固定时间" \? toApiDate\(scheduledAt\) : null/);
  assert.match(smartEntryPage, /timeMode === "截止窗口" \? !endsAt : !scheduledAt/);
  // 完成时限与通知来源不再由用户手填
  assert.doesNotMatch(smartEntryPage, /完成时限/);
  assert.doesNotMatch(smartEntryPage, /邮件 \/ 短信 \/ 网页/);
  assert.doesNotMatch(smartEntryPage, /setDeadlineWorkdays\(event\.target\.value/);
  assert.doesNotMatch(smartEntryPage, /setSource\(event\.target\.value\)/);
});

test("smart entry makes missing company and position names visible", () => {
  assert.doesNotMatch(smartEntryPage, /disabled=\{!canResolve \|\| creatingApplication \|\| !companyName\.trim\(\) \|\| !positionTitle\.trim\(\)\}/);
  assert.match(smartEntryPage, /请填写公司名称/);
  assert.match(smartEntryPage, /请填写岗位名称/);
  assert.match(styles, /\.extraction-clues input \{[^}]*font-size: 16px/);
  assert.doesNotMatch(styles, /\.extraction-clues input \+ input \{[^}]*font-size: 12px/);
});
