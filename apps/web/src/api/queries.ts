// Hook lấy dữ liệu. React Query lo phần lưu tạm, tải lại, và trạng thái đang tải / lỗi,
// nên các trang chỉ việc hiển thị.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, ApiError, type ArticleQuery } from "./client";

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

export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => unwrap(api.GET("/api/meta")),
  });
}

export function useOverview() {
  return useQuery({
    queryKey: ["overview"],
    queryFn: () => unwrap(api.GET("/api/stats/overview")),
  });
}

export function useArticles(query: ArticleQuery) {
  return useQuery({
    queryKey: ["articles", query],
    queryFn: () => unwrap(api.GET("/api/articles", { params: { query } })),
    placeholderData: keepPreviousData, // chuyển trang không bị nháy trắng
  });
}

export function useArticle(articleId: string) {
  return useQuery({
    queryKey: ["article", articleId],
    queryFn: () =>
      unwrap(api.GET("/api/articles/{article_id}", { params: { path: { article_id: articleId } } })),
  });
}
