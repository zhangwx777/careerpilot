import type { IntelChatMessage } from "./types";

export type ChatTurn = { user: IntelChatMessage | null; assistant: IntelChatMessage | null };

export function groupChatMessages(messages: IntelChatMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  const users = new Map<number, ChatTurn>();
  for (const message of messages) {
    if (message.role === "user") {
      const turn = { user: message, assistant: null };
      turns.push(turn);
      users.set(message.id, turn);
    } else {
      const last = turns[turns.length - 1];
      const turn = message.user_message_id ? users.get(message.user_message_id) : last;
      if (turn && !turn.assistant) turn.assistant = message;
      else turns.push({ user: null, assistant: message });
    }
  }
  return turns;
}
