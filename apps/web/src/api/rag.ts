// Hỏi đáp RAG (khung chat): /api/rag/status · /api/rag/conversations · /api/rag/messages (apps/api/rag_chat.py).
// Gửi câu hỏi trả 202 + lượt "queued"; máy chủ trả lời ở nền, web hỏi lại cho tới khi hết queued/running.
// Đi qua accountFetch vì cần cookie phiên + header X-CSRF-Token như các API tài khoản.
import { accountFetch } from "./auth";
import type { components } from "./schema";

type S = components["schemas"];
export type RagStatus = S["RAGChatStatus"];
export type RagConversation = S["RAGConversation"];
export type RagConversationDetail = S["RAGConversationDetail"];
export type RagMessage = S["RAGChatMessage"];
export type RagSource = S["RAGChatSource"];
export type RagAsk = S["RAGChatAsk"];
export type RagMessageStatus = RagMessage["status"];

export const PENDING: readonly RagMessageStatus[] = ["queued", "running"];
export const isPending = (m: Pick<RagMessage, "status">) => PENDING.includes(m.status);

export const ragApi = {
  status: () => accountFetch<RagStatus>("GET", "/api/rag/status"),
  conversations: () => accountFetch<RagConversation[]>("GET", "/api/rag/conversations"),
  conversation: (id: number) => accountFetch<RagConversationDetail>("GET", `/api/rag/conversations/${id}`),
  deleteConversation: (id: number) => accountFetch<void>("DELETE", `/api/rag/conversations/${id}`),
  ask: (body: RagAsk) => accountFetch<RagMessage>("POST", "/api/rag/messages", body),
  message: (id: number) => accountFetch<RagMessage>("GET", `/api/rag/messages/${id}`),
  cancel: (id: number) => accountFetch<RagMessage>("POST", `/api/rag/messages/${id}/cancel`),
};
