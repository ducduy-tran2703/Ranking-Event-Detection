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

const pad = (n: number) => String(n).padStart(2, "0");

/** Phần giờ VN của một chuỗi ISO có múi giờ: {date: "YYYY-MM-DD", hhmm: "HH:MM", ddmm: "DD/MM"}. */
export function vnClock(iso: string) {
  const s = new Date(Date.parse(iso) + 7 * 3_600_000).toISOString();
  return { date: s.slice(0, 10), hhmm: s.slice(11, 16), ddmm: `${s.slice(8, 10)}/${s.slice(5, 7)}`,
           hour: Number(s.slice(11, 13)) };
}

/** "10/09 11:23". */
export const fmtShort = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const c = vnClock(iso);
  return `${c.ddmm} ${c.hhmm}`;
};

/** "thứ Năm 10/09/2026". */
export function fmtWeekday(iso: string) {
  const d = new Date(iso);
  const wd = d.toLocaleDateString("vi-VN", { timeZone: VN, weekday: "long" });
  const c = vnClock(iso);
  return `${wd} ${c.ddmm}/${c.date.slice(0, 4)}`;
}

/** "2026-09-10" → "10/09". */
export const ddmm = (date: string) => `${date.slice(8, 10)}/${date.slice(5, 7)}`;

/** "2026-09-10" → "10/09/2026". */
export const ddmmyyyy = (date: string) => `${date.slice(8, 10)}/${date.slice(5, 7)}/${date.slice(0, 4)}`;

/** Số thập phân kiểu Việt Nam: 9,9 */
export const fmtDec = (x: number | null | undefined, digits = 1) =>
  x == null ? "—" : x.toLocaleString("vi-VN", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export const fmtPct = (part: number, whole: number, digits = 1) =>
  whole ? `${((part / whole) * 100).toLocaleString("vi-VN", { maximumFractionDigits: digits })}%` : "—";

/** Chữ viết tắt của tên người: "Lan Phương" → "LP". */
export function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts.length > 1 ? parts[parts.length - 2][0] : "";
  return (first + parts[parts.length - 1][0]).toUpperCase();
}

export { pad };
