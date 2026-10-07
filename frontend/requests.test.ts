import { test } from "node:test";
import assert from "node:assert/strict";
import { allPages, requestScope } from "./src/requests.ts";

test("late resource response cannot overwrite the new resource", async () => {
  const scope = requestScope();
  const current = scope.capture();
  let resolve!: (value: string) => void;
  const response = new Promise<string>((done) => { resolve = done; });
  let displayed = "new-resource";
  const pending = response.then((value) => { if (current()) displayed = value; });
  scope.invalidate();
  resolve("old-resource");
  await pending;
  assert.equal(displayed, "new-resource");
  assert.equal(scope.capture()(), true);
});

test("selectors and session task lists retrieve every page", async () => {
  const calls: number[] = [];
  const items = await allPages(async (page) => {
    calls.push(page);
    return { items: Array.from({ length: page === 3 ? 5 : 100 }, (_, i) => (page - 1) * 100 + i), page, page_size: 100, total: 205 };
  });
  assert.equal(items.length, 205);
  assert.deepEqual(calls, [1, 2, 3]);
});
