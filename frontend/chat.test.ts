import assert from "node:assert/strict";
import test from "node:test";
import { groupChatMessages } from "./src/chat.ts";
import type { IntelChatMessage } from "./src/types.ts";

const message = (id: number, role: "user" | "assistant", user_message_id?: number): IntelChatMessage => ({ id, role, user_message_id, content: "测试", status: "已完成", source_ids: [], created_at: "2026-10-07T00:00:00Z" });

test("parallel questions retain their own answers through server message IDs", () => {
  const turns = groupChatMessages([message(1, "user"), message(2, "user"), message(3, "assistant", 1), message(4, "assistant", 2)]);
  assert.deepEqual(turns.map((turn) => [turn.user?.id, turn.assistant?.id]), [[1, 3], [2, 4]]);
});

test("legacy sequential history still groups without a stored parent ID", () => {
  const turns = groupChatMessages([message(1, "user"), message(2, "assistant")]);
  assert.equal(turns[0].assistant?.id, 2);
});

test("missing parent never attaches an answer to another user's question", () => {
  const turns = groupChatMessages([message(1, "user"), message(3, "assistant", 2)]);
  assert.equal(turns[0].assistant, null);
  assert.equal(turns[1].user, null);
});
