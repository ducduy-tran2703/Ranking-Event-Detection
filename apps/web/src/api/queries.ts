// Hook lấy dữ liệu. React Query lo phần lưu tạm, tải lại, và trạng thái đang tải / lỗi,
// nên các trang chỉ việc hiển thị.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api, ApiError, type ArticleQuery, type EventQuery, type Granularity, type StatsFilter,
} from "./client";

/**
 * Lấy dữ liệu hoặc ném lỗi, dựa trên MÃ HTTP THẬT chứ không dựa trên các lỗi được khai báo trong
 * OpenAPI: backend vẫn có thể trả 404/500 ở những endpoint không khai báo lỗi nào.
 */
async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok || data === undefined) {
    throw new ApiError(response.status, error ?? response.statusText);
  }
  return data;
}

// ---------------------------------------------------------------- thông tin chung & độ tươi
export const useMeta = () =>
  useQuery({ queryKey: ["meta"], queryFn: () => unwrap(api.GET("/api/meta")) });

/** Tự kiểm tra mỗi 2 phút và mỗi khi quay lại tab: trên kho có file mới hơn dữ liệu đang dùng không. */
export const useFreshness = () =>
  useQuery({
    queryKey: ["freshness"],
    queryFn: () => unwrap(api.GET("/api/freshness")),
    refetchInterval: 120_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });

/** Tải lại dữ liệu từ kho vào backend, rồi làm mới MỌI biểu đồ và bảng đang hiển thị. */
export function useReload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/admin/reload")),
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

// ---------------------------------------------------------------- thống kê
export const useOverview = () =>
  useQuery({ queryKey: ["overview"], queryFn: () => unwrap(api.GET("/api/stats/overview")) });

export const useTimeline = (filter: StatsFilter, granularity: Granularity) =>
  useQuery({
    queryKey: ["timeline", filter, granularity],
    queryFn: () =>
      unwrap(api.GET("/api/stats/timeline", { params: { query: { ...filter, granularity } } })),
    placeholderData: keepPreviousData,
  });

export const useHourOfDay = (filter: StatsFilter) =>
  useQuery({
    queryKey: ["hour-of-day", filter],
    queryFn: () => unwrap(api.GET("/api/stats/hour-of-day", { params: { query: filter } })),
    placeholderData: keepPreviousData,
  });

export const useCategories = (filter: StatsFilter) =>
  useQuery({
    queryKey: ["categories", filter],
    queryFn: () => unwrap(api.GET("/api/stats/categories", { params: { query: filter } })),
    placeholderData: keepPreviousData,
  });

export const useQuality = () =>
  useQuery({ queryKey: ["quality"], queryFn: () => unwrap(api.GET("/api/stats/quality")) });

export const useFiles = () =>
  useQuery({ queryKey: ["files"], queryFn: () => unwrap(api.GET("/api/files")) });

// ---------------------------------------------------------------- bài báo
export const useArticles = (query: ArticleQuery) =>
  useQuery({
    queryKey: ["articles", query],
    queryFn: () => unwrap(api.GET("/api/articles", { params: { query } })),
    placeholderData: keepPreviousData, // chuyển trang không bị nháy trắng
  });

export const useArticle = (articleId: string) =>
  useQuery({
    queryKey: ["article", articleId],
    queryFn: () =>
      unwrap(api.GET("/api/articles/{article_id}", { params: { path: { article_id: articleId } } })),
  });

// ---------------------------------------------------------------- sự kiện (kết quả pipeline)
// Dữ liệu một lần chạy pipeline không đổi khi server đang chạy → lưu tạm lâu, không tự tải lại.
// Các *Options dùng chung cho hook và cho prefetch theo route (api/prefetch.ts) → cùng khoá, không gọi trùng.
const RUN_STALE = 10 * 60_000;

export const runOptions = () => ({
  queryKey: ["run"], queryFn: () => unwrap(api.GET("/api/runs/current")), staleTime: RUN_STALE,
});
export const trendTimesOptions = () => ({
  queryKey: ["trend-times"], queryFn: () => unwrap(api.GET("/api/trending/times")), staleTime: RUN_STALE,
});
/** t: "YYYY-MM-DDTHH:MM" giờ Việt Nam; bỏ trống → mốc mặc định của server. */
export const trendingOptions = (t: string | undefined) => ({
  queryKey: ["trending", t ?? ""],
  queryFn: () => unwrap(api.GET("/api/trending", { params: { query: t ? { t } : {} } })),
  staleTime: RUN_STALE,
});
export const eventsOptions = (query: EventQuery) => ({
  queryKey: ["events", query], queryFn: () => unwrap(api.GET("/api/events", { params: { query } })), staleTime: RUN_STALE,
});
export const eventOptions = (eventId: string) => ({
  queryKey: ["event", eventId],
  queryFn: () => unwrap(api.GET("/api/events/{event_id}", { params: { path: { event_id: eventId } } })),
  staleTime: RUN_STALE,
});
export const eventStatsOptions = (date?: string) => ({
  queryKey: ["event-stats", date ?? ""],
  queryFn: () => unwrap(api.GET("/api/events/stats", { params: { query: date ? { date } : {} } })),
  staleTime: RUN_STALE,
});

export const useRunInfo = () => useQuery(runOptions());
export const useTrendTimes = () => useQuery(trendTimesOptions());
export const useTrending = (t: string | undefined) =>
  useQuery({ ...trendingOptions(t), placeholderData: keepPreviousData });   // phát tự động không nháy trắng
export const useEvents = (query: EventQuery, enabled = true) =>
  useQuery({ ...eventsOptions(query), enabled, placeholderData: keepPreviousData });
export const useEvent = (eventId: string) => useQuery(eventOptions(eventId));

/** Phân bố kích thước / số báo / chuyên mục; `date` → thêm số liệu của ngày đó (trang chủ). */
export const useEventStats = (date?: string) => useQuery({ ...eventStatsOptions(date), placeholderData: keepPreviousData });

export const useMapDates = () =>
  useQuery({ queryKey: ["map-dates"], queryFn: () => unwrap(api.GET("/api/events/map/dates")), staleTime: RUN_STALE });

export const useEventMap = (date: string | undefined, enabled = true) =>
  useQuery({
    enabled,
    queryKey: ["event-map", date ?? ""],
    queryFn: () => unwrap(api.GET("/api/events/map", { params: { query: date ? { date } : {} } })),
    staleTime: RUN_STALE,
    placeholderData: keepPreviousData,
  });
