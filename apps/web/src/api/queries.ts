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
const RUN_STALE = 10 * 60_000;

export const useRunInfo = () =>
  useQuery({
    queryKey: ["run"],
    queryFn: () => unwrap(api.GET("/api/runs/current")),
    staleTime: RUN_STALE,
  });

export const useTrendTimes = () =>
  useQuery({
    queryKey: ["trend-times"],
    queryFn: () => unwrap(api.GET("/api/trending/times")),
    staleTime: RUN_STALE,
  });

/** t: "YYYY-MM-DDTHH:00" giờ Việt Nam; bỏ trống → mốc mặc định của server. */
export const useTrending = (t: string | undefined) =>
  useQuery({
    queryKey: ["trending", t ?? ""],
    queryFn: () => unwrap(api.GET("/api/trending", { params: { query: t ? { t } : {} } })),
    staleTime: RUN_STALE,
    placeholderData: keepPreviousData, // phát tự động không bị nháy trắng giữa các giờ
  });

export const useEvents = (query: EventQuery) =>
  useQuery({
    queryKey: ["events", query],
    queryFn: () => unwrap(api.GET("/api/events", { params: { query } })),
    staleTime: RUN_STALE,
    placeholderData: keepPreviousData,
  });

export const useEvent = (eventId: string) =>
  useQuery({
    queryKey: ["event", eventId],
    queryFn: () =>
      unwrap(api.GET("/api/events/{event_id}", { params: { path: { event_id: eventId } } })),
    staleTime: RUN_STALE,
  });
