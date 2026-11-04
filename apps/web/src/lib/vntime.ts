// Giờ Việt Nam (UTC+7, không đổi giờ mùa hè) cho thanh phát lại xu hướng: mọi mốc của backend là giờ tròn VN.
const HOUR = 3_600_000;
const VN_OFFSET = 7 * HOUR;
const VN = "Asia/Ho_Chi_Minh";

export const HOUR_MS = HOUR;

/** ms → "YYYY-MM-DDTHH:MM" theo giờ VN (gửi lên API dạng không múi giờ = giờ VN). */
export const vnLocal = (ms: number) => new Date(ms + VN_OFFSET).toISOString().slice(0, 16);

/** ms → {date: "YYYY-MM-DD", hour: 0–23} theo giờ VN. */
export function vnParts(ms: number) {
  const s = vnLocal(ms);
  return { date: s.slice(0, 10), hour: Number(s.slice(11, 13)) };
}

/** Ngày "YYYY-MM-DD" + giờ (giờ VN) → ms. */
export const fromVn = (date: string, hour: number) =>
  Date.parse(`${date}T${String(hour).padStart(2, "0")}:00:00+07:00`);

/** "T7, 19/09 08:00". */
export const fmtHourLong = (msOrIso: number | string) =>
  new Date(msOrIso).toLocaleString("vi-VN", {
    timeZone: VN, weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });

/** "19/09 08h" — nhãn trục ngắn. */
export function fmtHourShort(msOrIso: number | string) {
  const s = vnLocal(typeof msOrIso === "number" ? msOrIso : Date.parse(msOrIso));
  return `${s.slice(8, 10)}/${s.slice(5, 7)} ${s.slice(11, 13)}h`;
}

export const fmtScore = (x: number | null | undefined) =>
  x == null ? "—" : x.toLocaleString("vi-VN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

/**
 * Giá trị `?t=` trên URL → ms. Nhận cả dạng gọn "2026-09-14T10:00" (giờ VN) lẫn ISO đầy đủ có múi giờ
 * ("2026-09-14T10:00:00+07:00", "…Z" — đúng dạng API trả về). Không đọc được → NaN.
 */
export function parseUrlTime(value: string): number {
  if (/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) return Date.parse(value);
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  return m ? Date.parse(`${m[1]}T${m[2]}:${m[3]}:${m[4] ?? "00"}+07:00`) : NaN;
}
