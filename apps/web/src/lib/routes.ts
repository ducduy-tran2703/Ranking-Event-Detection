// Đường dẫn dùng chung. Trang kiểm soát dữ liệu cũ nằm trong khu quản trị: /admin/kho/…
export const KHO = "/admin/kho";
export const kho = {
  overview: KHO,
  time: `${KHO}/thoi-gian`,
  categories: `${KHO}/chuyen-muc`,
  quality: `${KHO}/chat-luong`,
  articles: `${KHO}/bai-bao`,
  article: (id: string) => `${KHO}/bai-bao/${encodeURIComponent(id)}`,
  sources: `${KHO}/nguon`,
};

/** Đường dẫn tương đối an toàn cho ?next= (chỉ trong trang, không "//host"). */
export function safeNext(next: string | null | undefined, fallback = "/me"): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : fallback;
}

export const loginHref = (next?: string) =>
  next && next !== "/login" ? `/login?next=${encodeURIComponent(next)}` : "/login";

export const eventHref = (id: string) => `/events/${encodeURIComponent(id)}`;

/** Trang Hỏi đáp; tham số chỉ để điền sẵn câu hỏi/khoảng ngày (trang tự xoá khỏi địa chỉ sau khi đọc). */
export function chatHref(prefill?: { q?: string; from?: string; to?: string; source?: string }) {
  const qs = new URLSearchParams(Object.entries(prefill ?? {}).filter(([, v]) => !!v) as [string, string][]).toString();
  return qs ? `/hoi-dap?${qs}` : "/hoi-dap";
}
