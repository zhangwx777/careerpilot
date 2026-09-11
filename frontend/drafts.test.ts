import assert from "node:assert/strict";
import test from "node:test";

import { clearDraft, loadDraft, loadSessionId, saveDraft, saveSessionId } from "./src/drafts.ts";

class MemoryStorage {
  private values = new Map<string, string>();

  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

test("restores and clears an unfinished draft", () => {
  const storage = new MemoryStorage();
  saveDraft(storage, "application", { companyName: "携程", title: "Agent工程师" });
  assert.deepEqual(loadDraft(storage, "application", {}), { companyName: "携程", title: "Agent工程师" });
  clearDraft(storage, "application");
  assert.deepEqual(loadDraft(storage, "application", {}), {});
});

test("merges defaults into an older partial draft", () => {
  const storage = new MemoryStorage();
  saveDraft(storage, "intel", { applicationId: 7, provider: "qwen", paste: "面经" });
  assert.deepEqual(
    loadDraft(storage, "intel", {
      applicationId: 0,
      provider: "qwen",
      paste: "",
      recognizedText: "",
      search: "",
      supplementWeb: true,
    }),
    {
      applicationId: 7,
      provider: "qwen",
      paste: "面经",
      recognizedText: "",
      search: "",
      supplementWeb: true,
    },
  );
});

test("restores only a valid active session id", () => {
  const storage = new MemoryStorage();
  saveSessionId(storage, "intel-session", 42);
  assert.equal(loadSessionId(storage, "intel-session"), 42);
  saveDraft(storage, "invalid-session", { id: 0 });
  assert.equal(loadSessionId(storage, "invalid-session"), null);
});
