"""Phát lại Silver như thể bài đang đến — THAY crawler khi chưa có crawler thật.

    python -m eventrank.ingest replay --start 2026-08-01T00:00+07:00 --speed 60 [--until …]

Đồng hồ giả lập chạy nhanh `speed` lần giờ thật (60 → 1 phút thật = 1 giờ giả lập). Mỗi nhịp (`tick`
giây thật): đẩy `sim_now` tới, upsert các bài có `published_at ≤ sim_now` (ingested_via = `replay`),
cập nhật `app_clock` (mode = replay) — cùng một transaction, nên ai đọc `app_now()` thấy đủ bài tới
đúng mốc đó. Nhịp đầu đưa vào mọi bài ≤ `start` (thế giới trước mốc bắt đầu, cần cho cửa sổ 48h).

Dừng (Ctrl+C) rồi chạy lại → TIẾP TỤC từ `sim_now` trong `app_clock` (không quay về `start`; muốn
quay lại thì `--reset`). Upsert idempotent nên đưa lại bài cũ không tạo bản mới.

An toàn: replay ghi vào DB RIÊNG (vd `eventrank_replay`, chọn bằng `--db-env`). DB đã có bài không
phải replay (import/crawler) → từ chối (trừ `--allow-mixed`): trộn bài thật với đồng hồ giả lập làm
worker/API hiểu sai "bây giờ".

Bộ nhớ: nạp + validate toàn bộ Silver một lần (~28,7 nghìn bài, vài trăm MB RAM) — đủ cho demo.
"""
from __future__ import annotations

import time
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg

from eventrank.ingest import clock as app_clock
from eventrank.ingest import sink
from eventrank.ingest.contract import VN, Article, Rejected, validate_article
from eventrank.ingest.jsonl import read_jsonl
from eventrank.ingest.sink import UpsertResult

VIA = "replay"


class ReplayError(RuntimeError):
    pass


@dataclass
class ReplayResult:
    sim_now: datetime
    resumed: bool
    ticks: int = 0
    counts: UpsertResult = field(default_factory=UpsertResult)


def load_silver(patterns: Iterable[str], *, known_sources: set[str],
                now: datetime) -> tuple[list[Article], UpsertResult]:
    """Silver đã qua hợp đồng, sắp theo published_at (bài trùng article_id: giữ bản đọc sau)."""
    by_id: dict[str, Article] = {}
    rejected = UpsertResult()
    for raw in read_jsonl(patterns):
        res = raw if isinstance(raw, Rejected) else validate_article(
            raw, known_sources=known_sources, now=now)
        if isinstance(res, Rejected):
            rejected.rejected += 1
            rejected.reject_reasons.update(res.codes)
        else:
            by_id[res.article_id] = res
    return sorted(by_id.values(), key=lambda a: a.published_at), rejected


def run_replay(conn: psycopg.Connection, articles: list[Article], *, start: datetime,
               speed: float, until: datetime | None = None, tick: float = 5.0,
               reset: bool = False, allow_mixed: bool = False,
               clock: Callable[[], float] = time.monotonic,
               sleep: Callable[[float], None] = time.sleep, max_ticks: int | None = None,
               log: Callable[[str], None] = print) -> ReplayResult:
    """`articles` phải đã sắp theo published_at (dùng `load_silver`)."""
    if start.tzinfo is None:
        raise ReplayError("--start phải có múi giờ, ví dụ 2026-08-01T00:00+07:00")
    if speed <= 0 or tick <= 0:
        raise ReplayError("speed và tick phải > 0")
    if not allow_mixed and conn.execute(
            "SELECT EXISTS (SELECT 1 FROM articles WHERE ingested_via <> %s)", (VIA,)
    ).fetchone()[0]:
        raise ReplayError("DB này đã có bài không phải replay (import/crawler). Phát lại vào "
                          "DB riêng "
                          "(createdb eventrank_replay; --db-env REPLAY_DATABASE_URL) hoặc "
                          "--allow-mixed nếu thật sự muốn trộn.")
    times = [a.published_at for a in articles]
    clk = app_clock.read_clock(conn)
    resumed = (not reset and clk.mode == "replay" and clk.sim_now is not None
               and clk.sim_now >= start)
    sim = clk.sim_now if resumed and clk.sim_now is not None else start
    end = until or (times[-1] if times else start)
    result = ReplayResult(sim_now=sim, resumed=resumed)

    def advance(lo: int, new_sim: datetime) -> int:
        hi = bisect_right(times, new_sim)
        with conn.transaction():
            result.counts.add(sink.upsert_articles(conn, articles[lo:hi], VIA))
            app_clock.set_replay(conn, new_sim, speed)
        return hi

    log(f"replay {'tiếp tục' if resumed else 'bắt đầu'} từ {sim.astimezone(VN).isoformat()} → "
        f"{end.astimezone(VN).isoformat()}, "
        f"×{speed:g}, nhịp {tick:g} s, {len(articles)} bài")
    idx = advance(0, sim)
    last = clock()
    while sim < end and (max_ticks is None or result.ticks < max_ticks):
        sleep(tick)
        t = clock()
        sim = min(end, sim + timedelta(seconds=(t - last) * speed))
        last = t
        before = result.counts.inserted
        idx = advance(idx, sim)
        result.ticks += 1
        if result.counts.inserted > before or result.ticks % 60 == 0:
            log(f"  {sim.astimezone(VN).isoformat(timespec='minutes')}  "
                f"+{result.counts.inserted - before} bài "
                f"(tổng mới {result.counts.inserted}, đã phát {idx}/{len(articles)})")
    result.sim_now = sim
    return result
