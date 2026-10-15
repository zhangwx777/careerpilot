import assert from "node:assert/strict";
import test from "node:test";

import { calendarDayKey, calendarMonthForDateKey, dateKey, monthGrid } from "./src/calendar.ts";
import { compareDashboardFeed } from "./src/dashboardFeed.ts";
import { toApiDate } from "./src/format.ts";
import type { DashboardFeedItem } from "./src/types.ts";

for (const timezone of ["UTC", "Asia/Shanghai", "America/Los_Angeles", "Pacific/Kiritimati"]) {
  test(`calendar keeps Shanghai dates across year boundaries: ${timezone}`, () => {
    const previousTimezone = process.env.TZ;
    process.env.TZ = timezone;
    try {
      const today = dateKey(new Date("2026-12-31T16:30:00Z"));
      assert.equal(today, "2027-01-01");
      const month = calendarMonthForDateKey(today);
      assert.equal(calendarDayKey(month), "2027-01-01");
      const days = monthGrid(month);
      assert.equal(days.length, 42);
      assert.equal(calendarDayKey(days[0]), "2026-12-28");
      assert.equal(calendarDayKey(days[41]), "2027-02-07");
      assert.equal(new Set(days.map(calendarDayKey)).size, 42);
      assert.equal(toApiDate(calendarDayKey(days[0]) + "T00:00"), "2026-12-27T16:00:00.000Z");
      assert.equal(days[0].getUTCDay(), 1);
      // March spans daylight-saving changes in several system timezones.
      const march = monthGrid(calendarMonthForDateKey("2026-03-08"));
      assert.equal(calendarDayKey(march[0]), "2026-02-23");
      assert.equal(calendarDayKey(march[41]), "2026-04-05");
    } finally {
      if (previousTimezone === undefined) delete process.env.TZ;
      else process.env.TZ = previousTimezone;
    }
  });
}

function item(id: number, kind: "preparation" | "timeline", scheduled_at: string | null, extra: Partial<DashboardFeedItem> = {}): DashboardFeedItem {
  return { id, kind, title: "测试事项", company_name: "测试公司", position_title: "后端", task_id: null, planner_session_id: null, timeline_node_id: null, detail: null, category: null, priority: null, node_type: null, status: "待处理", scheduled_at, alert_types: [], ...extra };
}

test("dashboard puts alerts first then interleaves preparation and timeline by instant", () => {
  const items = [
    item(1, "timeline", "2026-10-16T12:00:00+08:00"),
    item(2, "preparation", "2026-10-16T02:00:00Z"),
    item(3, "preparation", null, { priority: 3 }),
    item(4, "timeline", "2026-10-17T12:00:00+08:00", { alert_types: ["冲突"] }),
    item(5, "preparation", null, { priority: 1 }),
    item(6, "preparation", "2026-10-16T11:00:00+08:00"),
  ];
  assert.deepEqual([...items].sort(compareDashboardFeed).map((entry) => entry.id), [4, 2, 6, 1, 5, 3]);
});

test("dashboard preserves equal-time order and treats invalid dates as unscheduled", () => {
  const first = item(1, "timeline", "2026-10-16T12:00:00+08:00");
  const second = item(2, "timeline", "2026-10-16T04:00:00Z");
  assert.equal(compareDashboardFeed(first, first), 0);
  assert.equal(compareDashboardFeed(first, second), 0);
  assert.deepEqual([first, second].sort(compareDashboardFeed).map((entry) => entry.id), [1, 2]);
  const invalid = item(3, "preparation", "invalid");
  assert.deepEqual([invalid, first].sort(compareDashboardFeed).map((entry) => entry.id), [1, 3]);
});
