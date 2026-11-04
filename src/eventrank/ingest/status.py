"""`ingest status` (giờ hiển thị theo giờ Việt Nam): mỗi báo — lần chạy cuối, số bài mới 1h/24h, lỗi gần nhất; đồng hồ hệ thống.

"Bài mới 1h/24h": chế độ real đếm theo `crawled_at` (bài VÀO hệ thống trong 1h/24h qua); chế độ
replay đếm theo `published_at` trong 1h/24h trước `app_now()` (giờ giả lập).

Mục đích chính: thấy ngay "crawler chết âm thầm" (bẫy 10, mục 6.5) — RSS không lấy lại được quá khứ.
Cảnh báo in kèm: nguồn đã bật mà 2 giờ không có bài mới (ngưỡng mục 6.4 bước 9); lần chạy treo ở
`running` quá 1 giờ (tiến trình đã chết); lần chạy cuối `failed`/`blocked`.
"""
from __future__ import annotations

from typing import Any

import psycopg

from eventrank.ingest.clock import read_clock
from eventrank.ingest.contract import VN

STALE_HOURS = 2
STUCK_RUN_HOURS = 1

_SQL = """
SELECT s.source, s.enabled, s.crawler,
       r.crawler AS last_crawler, r.started_at AS last_started, r.status AS last_status,
       r.error AS last_error, r.n_new AS last_new, r.n_rejected AS last_rejected,
       (now() - r.started_at) > make_interval(hours => %(stuck)s) AND r.status = 'running'
           AS stuck,
       a.total, a.new_1h, a.new_24h, a.last_crawled, a.last_published,
       (SELECT max(e.started_at) FROM crawl_runs e
         WHERE e.source = s.source AND e.status IN ('failed', 'blocked')) AS last_error_at
FROM sources s
LEFT JOIN LATERAL (
    SELECT * FROM crawl_runs c WHERE c.source = s.source ORDER BY c.started_at DESC LIMIT 1
) r ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS total,
           count(*) FILTER (WHERE CASE WHEN %(replay)s
                                       THEN published_at > app_now() - interval '1 hour'
                                       ELSE crawled_at >= now() - interval '1 hour' END) AS new_1h,
           count(*) FILTER (WHERE CASE WHEN %(replay)s
                                       THEN published_at > app_now() - interval '24 hours'
                                       ELSE crawled_at >= now() - interval '24 hours' END)
               AS new_24h,
           max(crawled_at) AS last_crawled, max(published_at) AS last_published
    FROM articles WHERE articles.source = s.source
) a ON true
ORDER BY s.source
"""


def source_status(conn: psycopg.Connection) -> list[dict[str, Any]]:
    replay = read_clock(conn).mode == "replay"
    cur = conn.execute(_SQL, {"stuck": STUCK_RUN_HOURS, "replay": replay})
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _t(v) -> str:
    """Giờ Việt Nam, gọn."""
    return v.astimezone(VN).strftime("%d/%m %H:%M") if v else "—"


def format_status(conn: psycopg.Connection) -> str:
    rows = source_status(conn)
    clk = read_clock(conn)
    if clk.mode == "replay":
        clock_line = (f"Đồng hồ: replay, sim_now = {clk.sim_now.astimezone(VN).isoformat()} "
                      f"×{clk.speed:g}")
    else:
        clock_line = "Đồng hồ: real (giờ thật)"
    header = (f"{'nguồn':<12} {'bật':<4} {'lần chạy cuối':<14} {'trạng thái':<10} "
              f"{'mới 1h':>6} {'mới 24h':>7} {'tổng':>7} {'đăng mới nhất':<14} lỗi gần nhất")
    out = [clock_line, "", header]
    warns = []
    for r in rows:
        err = (r["last_error"] or "")[:60] if r["last_status"] in ("failed", "blocked") else ""
        out.append(f"{r['source']:<12} {'có' if r['enabled'] else '—':<4} "
                   f"{_t(r['last_started']):<14} {r['last_status'] or '—':<10} "
                   f"{r['new_1h'] or 0:>6} {r['new_24h'] or 0:>7} {r['total'] or 0:>7} "
                   f"{_t(r['last_published']):<14} {err}")
        if r["stuck"]:
            warns.append(f"{r['source']}: lần chạy bắt đầu {_t(r['last_started'])} vẫn 'running' "
                         f"> {STUCK_RUN_HOURS} giờ — tiến trình có thể đã chết")
        if r["last_status"] in ("failed", "blocked"):
            warns.append(f"{r['source']}: lần chạy cuối {r['last_status']}: {r['last_error']}")
        if r["enabled"] and clk.mode == "real" and not r["new_1h"] and (
                r["last_crawled"] is None or
                conn.execute("SELECT %s < now() - make_interval(hours => %s)",
                             (r["last_crawled"], STALE_HOURS)).fetchone()[0]):
            warns.append(f"{r['source']}: đã bật nhưng {STALE_HOURS} giờ không có bài mới")
    if warns:
        out += ["", "CẢNH BÁO:"] + [f"  - {w}" for w in warns]
    return "\n".join(out)
