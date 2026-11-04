// Hook React Query cho khu quản trị (tách riêng để mã quản trị không vào gói JS ban đầu).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "./admin";

// ------------------------------------------------------------------ quản trị
export const useAdminUsers = () => useQuery({ queryKey: ["admin", "users"], queryFn: () => adminApi.users() });
export const useAdminFeedback = () => useQuery({ queryKey: ["admin", "feedback"], queryFn: () => adminApi.feedback() });
export const useAdminOutbox = () => useQuery({ queryKey: ["admin", "outbox"], queryFn: () => adminApi.outbox() });
export const useAdminTokens = () => useQuery({ queryKey: ["admin", "tokens"], queryFn: () => adminApi.tokens() });
export function useAdminAction<V, R = unknown>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: ["admin"] }) });
}
export { adminApi };
