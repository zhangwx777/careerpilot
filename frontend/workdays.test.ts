import assert from "node:assert/strict";
import test from "node:test";

import { deadlineAfterWorkdays } from "./src/workdays.ts";

test("从起始日后的第三个工作日截止", () => {
  assert.equal(deadlineAfterWorkdays("2026-09-09T09:30", 3), "2026-09-14T23:59");
});

test("周末不计入工作日", () => {
  assert.equal(deadlineAfterWorkdays("2026-09-11T09:30", 3), "2026-09-16T23:59");
});

test("workdays 为 0 时不跨日", () => {
  assert.equal(deadlineAfterWorkdays("2026-09-11T23:59", 0), "2026-09-11T23:59");
});

test("临近午夜仍按日期计算", () => {
  assert.equal(deadlineAfterWorkdays("2026-09-11T23:59", 1), "2026-09-14T23:59");
});

test("月末跨年", () => {
  assert.equal(deadlineAfterWorkdays("2026-12-31T23:59", 1), "2027-01-01T23:59");
});
