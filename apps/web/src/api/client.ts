// Cửa duy nhất để gọi backend. Mọi đường dẫn và tham số đều được kiểm tra kiểu
// theo src/api/schema.d.ts — file này SINH TỰ ĐỘNG bằng `make types`, không sửa tay.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

// baseUrl rỗng: gọi "/api/..." cùng địa chỉ với trang web.
// Khi phát triển, Vite chuyển tiếp "/api" sang FastAPI (xem vite.config.ts).
export const api = createClient<paths>({ baseUrl: "" });

type Schemas = components["schemas"];
export type Meta = Schemas["Meta"];
export type Overview = Schemas["Overview"];
export type ArticleSummary = Schemas["ArticleSummary"];
export type ArticleDetail = Schemas["ArticleDetail"];
export type Quality = Schemas["Quality"];
export type IssueCounts = Schemas["IssueCounts"];
export type RawSourceValue = Schemas["RawSourceValue"];
export type FileInfo = Schemas["FileInfo"];
export type Freshness = Schemas["Freshness"];
export type RunInfo = Schemas["RunInfo"];
export type TrendTimes = Schemas["TrendTimes"];
export type Trending = Schemas["Trending"];
export type TrendItem = Schemas["TrendItem"];
export type EventSummary = Schemas["EventSummary"];
export type EventDetail = Schemas["EventDetail"];
export type EventPoint = Schemas["EventPoint"];
export type EventStats = Schemas["EventStats"];
export type EventMap = Schemas["EventMap"];
export type MapEvent = Schemas["MapEvent"];
export type SourceOverview = Schemas["SourceOverview"];

type QueryOf<P extends keyof paths> = paths[P] extends { get: { parameters: { query?: infer Q } } }
  ? NonNullable<Q>
  : never;
export type ArticleQuery = QueryOf<"/api/articles">;
export type EventQuery = QueryOf<"/api/events">;
export type StatsFilter = QueryOf<"/api/stats/categories">; // source, category, q, date_from, date_to, issue
export type Granularity = "day" | "hour";

/** Câu tiếng Việt cho người đọc theo mã HTTP; `detail` của API chỉ dùng khi là CHUỖI (không bao giờ in JSON). */
export function apiMessage(status: number, detail: unknown): string {
  const raw = typeof detail === "string" ? detail
    : detail && typeof detail === "object" && typeof (detail as { detail?: unknown }).detail === "string"
      ? (detail as { detail: string }).detail : "";
  const text = raw.trim().replace(/\s+/g, " ").slice(0, 300);
  const base: Record<number, string> = {
    400: "Yêu cầu không hợp lệ.", 401: "Bạn cần đăng nhập.", 403: "Không có quyền xem nội dung này.",
    404: "Không tìm thấy dữ liệu.", 422: "Tham số trên đường dẫn không hợp lệ.",
    503: "Máy chủ chưa sẵn sàng phục vụ dữ liệu này.",
  };
  const head = base[status] ?? (status >= 500 ? `Máy chủ gặp lỗi (mã ${status}). Thử lại sau.` : `Lỗi ${status}.`);
  return text && !text.startsWith("{") && !text.startsWith("[") ? `${head} ${text}` : head;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(apiMessage(status, detail));
  }
}
