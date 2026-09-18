import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styles = readFileSync(new URL("./src/styles.css", import.meta.url), "utf8");

test("intel chat has a dedicated always-visible vertical scrollbar", () => {
  const rule = styles.match(/\.intel-chat-history\s*\{([^}]*)\}/)?.[1] ?? "";
  assert.match(rule, /overflow-y:\s*scroll/);
  assert.match(rule, /scrollbar-gutter:\s*stable/);
  assert.match(rule, /height:\s*(?:min|clamp)\(/);
});
