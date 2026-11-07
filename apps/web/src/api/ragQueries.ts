// Hook React Query cho trang Hỏi đáp. Trang chỉ dùng các hook này (không gọi ragApi trực tiếp).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCurrentUser } from "./accountQueries";
import { isPending, ragApi, type RagAsk, type RagConversationDetail } from "./rag";

const POLL_MS = 2500;

export function useRagStatus() {
  const { data: user } = useCurrentUser();
  return useQuery({ queryKey: ["rag", "status", user?.id ?? null], queryFn: () => ragApi.status(), staleTime: 30_000 });
}

export function useConversations() {
  const { data: user } = useCurrentUser();
  return useQuery({
    queryKey: ["me", user?.id, "rag", "conversations"], queryFn: () => ragApi.conversations(), enabled: !!user,
  });
}

/** Một cuộc trò chuyện; tự hỏi lại mỗi 2,5 giây khi còn lượt đang chờ trả lời. */
export function useConversation(id: number | null) {
  const { data: user } = useCurrentUser();
  return useQuery({
    queryKey: ["me", user?.id, "rag", "conversation", id],
    queryFn: () => ragApi.conversation(id as number),
    enabled: !!user && id != null,
    refetchInterval: (q) => {
      const d = q.state.data as RagConversationDetail | undefined;
      return d?.messages.some(isPending) ? POLL_MS : false;
    },
  });
}

export function useAsk() {
  const qc = useQueryClient();
  const { data: user } = useCurrentUser();
  return useMutation({
    mutationFn: (body: RagAsk) => ragApi.ask(body),
    onSuccess: (msg) => {
      qc.invalidateQueries({ queryKey: ["me", user?.id, "rag", "conversations"] });
      qc.invalidateQueries({ queryKey: ["me", user?.id, "rag", "conversation", msg.conversation_id] });
      qc.invalidateQueries({ queryKey: ["rag", "status"] });
    },
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  const { data: user } = useCurrentUser();
  return useMutation({
    mutationFn: (id: number) => ragApi.deleteConversation(id),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: ["me", user?.id, "rag", "conversation", id] });
      qc.invalidateQueries({ queryKey: ["me", user?.id, "rag", "conversations"] });
    },
  });
}

/** Dừng lượt đang chờ/đang chạy (máy chủ bỏ kết quả nếu mô hình trả về muộn). */
export function useCancel() {
  const qc = useQueryClient();
  const { data: user } = useCurrentUser();
  return useMutation({
    mutationFn: (messageId: number) => ragApi.cancel(messageId),
    onSettled: (msg) => {
      qc.invalidateQueries({ queryKey: ["me", user?.id, "rag", "conversations"] });
      if (msg) qc.invalidateQueries({ queryKey: ["me", user?.id, "rag", "conversation", msg.conversation_id] });
      else qc.invalidateQueries({ queryKey: ["me", user?.id, "rag", "conversation"] });
    },
  });
}
