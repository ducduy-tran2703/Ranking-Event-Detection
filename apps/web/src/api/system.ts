// Cài đặt hệ thống (khu quản trị): /api/admin/system/* (apps/api/system_settings.py) — chỉ quản trị viên.
// Lịch cào báo chuyển tiếp sang dịch vụ crawler :8002; đồng bộ RAG và worker sự kiện lưu trong Postgres (system_settings).
// Đi qua accountFetch vì cần cookie phiên + header X-CSRF-Token. Không có bản giả lập: trang báo lỗi khi bật AUTH_MOCK.
import { accountFetch } from "./auth";
import type { components } from "./schema";

type S = components["schemas"];
export type SystemSettings = S["SystemSettings"];
export type CrawlerSettings = S["CrawlerSettings"];
export type CrawlerScheduleBody = S["CrawlerScheduleBody"];
export type CrawlerRunAccepted = S["CrawlerRunAccepted"];
export type RagSyncBlock = S["RagSyncBlock"];
export type RagSyncSettings = S["RagSyncSettings"];
export type RagSyncRunAccepted = S["RagSyncRunAccepted"];
export type EventWorkerBlock = S["EventWorkerBlock"];
export type EventWorkerSettings = S["EventWorkerSettings"];
export type SystemRun = S["SystemRun"];

const BASE = "/api/admin/system";

export const systemApi = {
  settings: () => accountFetch<SystemSettings>("GET", `${BASE}/settings`),
  saveRagSync: (body: RagSyncSettings) => accountFetch<RagSyncBlock>("PUT", `${BASE}/settings/rag-sync`, body),
  saveEventWorker: (body: EventWorkerSettings) => accountFetch<EventWorkerBlock>("PUT", `${BASE}/settings/event-worker`, body),
  patchCrawlerSchedule: (body: CrawlerScheduleBody) => accountFetch<CrawlerSettings>("PATCH", `${BASE}/crawler/schedule`, body),
  runCrawler: (sources?: string[]) => accountFetch<CrawlerRunAccepted>("POST", `${BASE}/crawler/run`, sources ? { sources } : {}),
  runRagSync: () => accountFetch<RagSyncRunAccepted>("POST", `${BASE}/rag-sync/run`),
};
