import assert from "node:assert/strict";
import test from "node:test";

import { formatDateTime, toApiDate, toShanghaiInput } from "./src/format.ts";
import { deadlineAfterWorkdays } from "./src/workdays.ts";

for (const timezone of ["UTC", "Asia/Shanghai", "America/Los_Angeles", "Pacific/Kiritimati"]) {
  test(`Shanghai display and form round trips are independent of host timezone: ${timezone}`, () => {
    const previousTimezone = process.env.TZ;
    process.env.TZ = timezone;
    try {
      const instant = "2026-12-31T16:30:00Z";
      assert.equal(formatDateTime(instant), "1月1日 周五 00:30");
      assert.equal(toShanghaiInput(instant), "2027-01-01T00:30");
      assert.equal(toApiDate(toShanghaiInput(instant)), "2026-12-31T16:30:00.000Z");
      assert.equal(toApiDate("2027-01-01T00:30+08:00"), "2026-12-31T16:30:00.000Z");
      assert.equal(toApiDate(instant), "2026-12-31T16:30:00.000Z");
      assert.equal(toShanghaiInput("2026-09-11T16:00:00Z"), "2026-09-12T00:00");
      assert.equal(deadlineAfterWorkdays(toShanghaiInput("2026-09-11T16:00:00Z"), 1), "2026-09-14T23:59");
      assert.equal(deadlineAfterWorkdays("2026-03-06T23:59", 1), "2026-03-09T23:59");
    } finally {
      if (previousTimezone === undefined) delete process.env.TZ;
      else process.env.TZ = previousTimezone;
    }
  });
}

test("missing dates remain empty rather than becoming the current time", () => {
  assert.equal(toShanghaiInput(null), "");
  assert.equal(toApiDate(""), null);
  assert.equal(formatDateTime(null), "时间待补充");
});
