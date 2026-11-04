// Gọi trước API của trang ngay khi đổi route — song song với việc tải gói JS lười của trang (bỏ "thác nước":
// trước đây trang chủ chỉ gọi /api/trending SAU khi tải xong HomePage.js). Khoá trùng với hook → không gọi hai lần.
import type { QueryClient } from "@tanstack/react-query";
import { parseUrlTime, vnLocal } from "../lib/vntime";
import { eventOptions, eventStatsOptions, eventsOptions, runOptions, trendTimesOptions, trendingOptions } from "./queries";

const HOUR = 3_600_000;

/** Mốc "YYYY-MM-DDTHH:00" (giờ VN) từ ?t= hợp lệ; không hợp lệ → undefined. */
export function urlHour(tParam: string | null): string | undefined {
  if (!tParam) return undefined;
  const ms = parseUrlTime(tParam);
  return Number.isFinite(ms) ? vnLocal(Math.floor(ms / HOUR) * HOUR) : undefined;
}

export function prefetchRoute(qc: QueryClient, pathname: string, search: string) {
  const p = new URLSearchParams(search);
  const go = (o: { queryKey: unknown[]; queryFn: () => Promise<unknown>; staleTime: number }) => { void qc.prefetchQuery(o); };
  go(runOptions());
  if (pathname === "/") {
    go(trendTimesOptions());
    const t = p.get("t") ? urlHour(p.get("t")) : undefined;
    if (!p.get("t") || t) go(trendingOptions(t && p.get("t") ? vnLocal(parseUrlTime(p.get("t")!)) : undefined));
    if (t) {
      const day = t.slice(0, 10);
      go(eventStatsOptions(day));
      go(eventsOptions({ sort: "first_seen", min_size: 2, first_from: `${day}T00:00`, first_to: t, page_size: 5 }));
    }
  }
  const m = /^\/events\/(E\d{8}-[0-9a-f]{8})$/.exec(pathname);
  if (m) go(eventOptions(m[1]));
  if (pathname === "/chuyen-muc" || pathname === "/du-lieu/gom-cum") go(eventStatsOptions());
}
