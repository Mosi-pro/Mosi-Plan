import { api, ApiError } from "./api";
import type { PendingAction } from "./types";

export type ChatEvent =
  | { type: "status"; state: "thinking" | "acting"; label?: string }
  | { type: "backend"; name: string }
  | { type: "tool"; name: string; label: string }
  | { type: "tool_result"; name: string; ok: boolean; status?: string; error?: string }
  | { type: "delta"; text: string }
  | { type: "done"; message_id: number; content: string; error: string | null; pending_actions: PendingAction[] };

/** Sendet eine Nachricht und liest den SSE-Stream des Backends. */
export async function streamChat(conversationId: number, content: string, viaVoice: boolean, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
  const res = await api.raw("POST", `/api/conversations/${conversationId}/messages`, { content, via_voice: viaVoice });
  if (!res.body) throw new ApiError(500, "Keine Antwort vom Server.");
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let done: ChatEvent | null = null;
  signal?.addEventListener("abort", () => reader.cancel());
  for (;;) {
    const { value, done: end } = await reader.read();
    if (end) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        try {
          const ev = JSON.parse(line.slice(6)) as ChatEvent;
          if (ev.type === "done") done = ev;
          onEvent(ev);
        } catch {
          /* unvollständige Zeile */
        }
      }
    }
  }
  if (!done) throw new ApiError(0, "Die Verbindung zum Assistenten wurde unterbrochen.");
  return done as Extract<ChatEvent, { type: "done" }>;
}

const ACTIVE_KEY = "mosi.activeConversation";
export const getActiveConversation = () => {
  try { return Number(localStorage.getItem(ACTIVE_KEY)) || null; } catch { return null; }
};
export const setActiveConversation = (id: number) => {
  try { localStorage.setItem(ACTIVE_KEY, String(id)); } catch { /* ignorieren */ }
};
export async function ensureConversation(): Promise<number> {
  const id = getActiveConversation();
  if (id) {
    try { await api.get(`/api/conversations/${id}`); return id; } catch { /* gelöscht */ }
  }
  const c = await api.post<{ id: number }>("/api/conversations");
  setActiveConversation(c.id);
  return c.id;
}
