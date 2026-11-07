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
export type FileInfo = Schemas["FileInfo"];
export type Freshness = Schemas["Freshness"];

type QueryOf<P extends keyof paths> = paths[P] extends { get: { parameters: { query?: infer Q } } }
  ? NonNullable<Q>
  : never;
export type ArticleQuery = QueryOf<"/api/articles">;
export type StatsFilter = QueryOf<"/api/stats/categories">; // source, category, q, date_from, date_to, issue
export type Granularity = "day" | "hour";

export class ApiError extends Error {
  constructor(public status: number, detail: unknown) {
    super(`Lỗi ${status}: ${typeof detail === "object" ? JSON.stringify(detail) : String(detail)}`);
  }
}
