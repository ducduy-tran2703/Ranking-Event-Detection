const VN = "Asia/Ho_Chi_Minh";

export const fmtInt = (n: number | null | undefined) => (n ?? 0).toLocaleString("vi-VN");

export const fmtDateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("vi-VN", { timeZone: VN, dateStyle: "short", timeStyle: "short" }) : "—";

export const fmtMB = (bytes: number) => `${(bytes / 1e6).toFixed(1)} MB`;

/** "5 phút trước", "3 giờ trước", "2 ngày trước". */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const minutes = Math.max(0, (now - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "vừa xong";
  if (minutes < 60) return `${Math.round(minutes)} phút trước`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} giờ trước`;
  return `${Math.round(minutes / 1440)} ngày trước`;
}

export const ageHours = (iso: string, now = Date.now()) => (now - new Date(iso).getTime()) / 3.6e6;
