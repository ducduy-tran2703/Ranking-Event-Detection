// Hook React Query cho khu quản trị (tách riêng để mã quản trị không vào gói JS ban đầu).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "./admin";
import { systemApi, type CrawlerScheduleBody, type EventWorkerSettings, type RagSyncSettings } from "./system";

// ------------------------------------------------------------------ quản trị
export const useAdminUsers = () => useQuery({ queryKey: ["admin", "users"], queryFn: () => adminApi.users() });
export const useAdminFeedback = () => useQuery({ queryKey: ["admin", "feedback"], queryFn: () => adminApi.feedback() });
export const useAdminOutbox = () => useQuery({ queryKey: ["admin", "outbox"], queryFn: () => adminApi.outbox() });
export const useAdminTokens = () => useQuery({ queryKey: ["admin", "tokens"], queryFn: () => adminApi.tokens() });
export function useAdminAction<V, R = unknown>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: ["admin"] }) });
}

// ------------------------------------------------------------------ cài đặt hệ thống (/admin/cai-dat)
const SYSTEM_KEY = ["admin", "system"] as const;
/** Tự tải lại 10 giây/lần khi có lượt cào hoặc đồng bộ RAG đang chạy, 30 giây/lần khi rảnh. */
export const useSystemSettings = () => useQuery({
  queryKey: SYSTEM_KEY, queryFn: () => systemApi.settings(),
  refetchInterval: (q) => {
    const d = q.state.data;
    return d && (d.rag_sync.running || d.crawler.active_job_id) ? 10_000 : 30_000;
  },
});
function useSystemAction<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: SYSTEM_KEY }) });
}
export const useSaveRagSync = () => useSystemAction((v: RagSyncSettings) => systemApi.saveRagSync(v));
export const useSaveEventWorker = () => useSystemAction((v: EventWorkerSettings) => systemApi.saveEventWorker(v));
export const usePatchCrawlerSchedule = () => useSystemAction((v: CrawlerScheduleBody) => systemApi.patchCrawlerSchedule(v));
export const useRunCrawler = () => useSystemAction((sources?: string[]) => systemApi.runCrawler(sources));
export const useRunRagSync = () => useSystemAction((_: void) => systemApi.runRagSync());
export { adminApi };
