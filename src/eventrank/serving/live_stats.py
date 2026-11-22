"""Số liệu trực tiếp của máy chủ cho trang web "Dữ liệu máy chủ" (`GET /api/live/overview`).

Khác `/api/stats/*` (đọc kho Silver tĩnh), mọi số ở đây đọc từ Postgres đang chạy: bài crawler vừa nạp, các lượt
cào (`crawl_runs`), các bước worker (`worker_runs`), lớp sự kiện, chỉ mục RAG và dung lượng bảng. Thêm phần lịch cào
của dịch vụ crawler (:8002) nếu dịch vụ đó trả lời; không trả lời thì phần đó là None, phần còn lại vẫn có.

Mốc thời gian là `now()` của Postgres (giờ thật). Đồng hồ ở chế độ replay thì `clock_mode = "replay"` và web ghi chú
rằng các cửa sổ 1h/24h vẫn tính theo giờ thật (riêng số "mới 1h/24h" của từng báo đi theo `ingest status`).

Đo trên DB chính 10/11/2026 (30.161 bài, 20.987 sự kiện): ~0,4 s khi bộ đệm Postgres đã nóng, 3,4 s lần đầu (lạnh);
API giữ kết quả 15 s.
Không đếm số từ của thân bài: quét `content_text` mất ~9 s.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any

import psycopg

from eventrank.ingest.clock import read_clock
from eventrank.ingest.status import source_status

HOURS = 48                      # cột theo giờ: 48 giờ gần nhất, tính cả giờ hiện tại
DAYS = 14                       # bảng nhiệt theo ngày đăng
EVENT_WINDOW_DAYS = 7           # phân bố sự kiện: sự kiện có bài trong 7 ngày qua (bằng pending_max_age_days)
RECENT_CRAWL_RUNS = 40
RECENT_WORKER_RUNS = 120        # đủ cho ~30 vòng đầy đủ embed → recluster → name → trend (không gồm rag_sync:
                                # bộ lập lịch RAG ghi cùng bảng nhưng không thuộc vòng worker sự kiện)
WORKER_ROUNDS = 20
TOP_EVENTS = 10
CRAWLER_JOBS = 5
FLAGS = ("missing_author", "no_body", "short_body", "missing_sapo")
SIZE_BUCKETS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 9), (10, 19), (20, None))
TABLES = ("articles", "article_embeddings", "events", "event_articles", "event_names", "event_assignment_log",
          "trend_scores", "article_ner", "rag_chunks", "crawl_runs", "worker_runs")


def _rows(conn: psycopg.Connection, sql: str, params: Any = None) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _series(rows: list[dict[str, Any]], key: str, slots: list, slot_key: str = "slot") -> dict[str, list[int]]:
    """{source: [đếm theo từng slot]} — slot không có bài là 0."""
    index = {s: i for i, s in enumerate(slots)}
    out: dict[str, list[int]] = {}
    for r in rows:
        i = index.get(r[slot_key])
        if i is not None:
            out.setdefault(r["source"], [0] * len(slots))[i] = int(r[key])
    return out


def _totals(conn: psycopg.Connection) -> dict[str, Any]:
    t = _rows(conn, """
        SELECT (SELECT count(*) FROM articles) AS articles,
               (SELECT count(*) FROM articles WHERE crawled_at >= now() - interval '1 hour') AS new_1h,
               (SELECT count(*) FROM articles WHERE crawled_at >= now() - interval '24 hours') AS new_24h,
               (SELECT min(published_at) FROM articles) AS first_published,
               (SELECT max(published_at) FROM articles) AS last_published,
               (SELECT max(crawled_at) FROM articles) AS last_crawled,
               (SELECT count(*) FROM article_embeddings) AS embedded,
               (SELECT count(*) FROM articles a WHERE NOT EXISTS
                    (SELECT 1 FROM article_embeddings e WHERE e.article_id = a.article_id)) AS not_embedded,
               (SELECT count(DISTINCT article_id) FROM event_articles) AS in_events,
               (SELECT count(DISTINCT article_id) FROM rag_chunks) AS rag_articles,
               (SELECT count(*) FROM rag_chunks) AS rag_chunks,
               (SELECT count(*) FROM events WHERE created_at >= now() - interval '24 hours'
                                              AND status <> 'merged') AS events_new_24h,
               pg_database_size(current_database()) AS db_bytes
    """)[0]
    t["events_by_status"] = {r["status"]: int(r["n"]) for r in
                             _rows(conn, "SELECT status, count(*) AS n FROM events GROUP BY status")}
    return t


def _sources(conn: psycopg.Connection) -> list[dict[str, Any]]:
    flags = {r["source"]: r for r in _rows(conn, f"""
        SELECT source, {", ".join(f"count(*) FILTER (WHERE '{f}' = ANY(quality_flags)) AS {f}" for f in FLAGS)},
               min(published_at) AS first_published
        FROM articles GROUP BY source""")}
    runs = {r["source"]: r for r in _rows(conn, """
        SELECT source, count(*) AS runs_24h,
               count(*) FILTER (WHERE status IN ('failed', 'blocked')) AS failed_24h,
               coalesce(sum(n_seen), 0) AS seen_24h, coalesce(sum(n_rejected), 0) AS rejected_24h
        FROM crawl_runs WHERE started_at >= now() - interval '24 hours' GROUP BY source""")}
    names = {r["source"]: r["display_name"] for r in _rows(conn, "SELECT source, display_name FROM sources")}
    out = []
    for s in source_status(conn):
        f, r = flags.get(s["source"], {}), runs.get(s["source"], {})
        out.append({
            "source": s["source"], "display_name": names.get(s["source"], s["source"]),
            "total": int(s["total"] or 0), "new_1h": int(s["new_1h"] or 0), "new_24h": int(s["new_24h"] or 0),
            "first_published": f.get("first_published"), "last_published": s["last_published"],
            "last_crawled": s["last_crawled"], "last_run_at": s["last_started"], "last_run_status": s["last_status"],
            "last_error": s["last_error"] if s["last_status"] in ("failed", "blocked") else None,
            "stuck": bool(s["stuck"]),
            "runs_24h": int(r.get("runs_24h", 0)), "failed_24h": int(r.get("failed_24h", 0)),
            "seen_24h": int(r.get("seen_24h", 0)), "rejected_24h": int(r.get("rejected_24h", 0)),
            "flags": {k: int(f.get(k, 0)) for k in FLAGS},
        })
    return out


def _hourly(conn: psycopg.Connection, now: datetime) -> dict[str, Any]:
    end = now.replace(minute=0, second=0, microsecond=0)
    hours = [end - timedelta(hours=HOURS - 1 - i) for i in range(HOURS)]
    start = hours[0]
    q = "SELECT source, date_trunc('hour', {col}) AS slot, count(*) AS n FROM articles " \
        "WHERE {col} >= %(start)s GROUP BY 1, 2"
    ingested = _series(_rows(conn, q.format(col="crawled_at"), {"start": start}), "n", hours)
    published = _series(_rows(conn, q.format(col="published_at"), {"start": start}), "n", hours)
    created = [0] * HOURS
    for r in _rows(conn, "SELECT date_trunc('hour', created_at) AS slot, count(*) AS n FROM events "
                         "WHERE created_at >= %(start)s AND status <> 'merged' GROUP BY 1", {"start": start}):
        if r["slot"] in hours:
            created[hours.index(r["slot"])] = int(r["n"])
    sources = sorted(set(ingested) | set(published))
    return {"hours": hours, "events_created": created,
            "series": [{"source": s, "ingested": ingested.get(s, [0] * HOURS),
                        "published": published.get(s, [0] * HOURS)} for s in sources]}


def _daily(conn: psycopg.Connection) -> dict[str, Any]:
    rows = _rows(conn, """
        SELECT source, (published_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS slot, count(*) AS n
        FROM articles
        WHERE published_at >= ((now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - %(back)s) AT TIME ZONE 'Asia/Ho_Chi_Minh'
        GROUP BY 1, 2""", {"back": DAYS - 1})
    today = conn.execute("SELECT (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date").fetchone()[0]
    days = [today - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]
    counts = _series(rows, "n", days)
    return {"days": days, "series": [{"source": s, "counts": c} for s, c in sorted(counts.items())]}


def _crawl_runs(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return _rows(conn, """
        SELECT run_id, source, crawler, started_at, finished_at, status, n_seen, n_new, n_updated, n_unchanged,
               n_rejected, reject_reasons, left(error, 300) AS error,
               extract(epoch FROM finished_at - started_at)::float8 AS seconds
        FROM crawl_runs ORDER BY started_at DESC LIMIT %s""", (RECENT_CRAWL_RUNS,))


def group_rounds(runs: list[dict[str, Any]], limit: int = WORKER_ROUNDS) -> list[dict[str, Any]]:
    """Gom các dòng `worker_runs` thành vòng worker (embed → recluster → name → trend, bước không có việc thì
    không ghi dòng). Vòng mới bắt đầu khi gặp `embed`, khi bước đã có trong vòng hiện tại, hoặc khi cách đầu vòng
    quá 10 phút. `runs` có thể ở bất kỳ thứ tự nào; trả về vòng mới nhất trước."""
    rounds: list[dict[str, Any]] = []
    for r in sorted(runs, key=lambda x: (x["started_at"], x["run_id"])):
        cur = rounds[-1] if rounds else None
        if (cur is None or r["step"] in ("embed", "import") or r["step"] in cur["steps"]
                or (r["started_at"] - cur["started_at"]).total_seconds() > 600):
            cur = {"started_at": r["started_at"], "finished_at": r["finished_at"], "status": "ok", "steps": {}}
            rounds.append(cur)
        cur["steps"][r["step"]] = {"run_id": r["run_id"], "status": r["status"], "seconds": r["seconds"],
                                   "stats": r["stats"] or {}, "error": r["error"]}
        if r["finished_at"] and (cur["finished_at"] is None or r["finished_at"] > cur["finished_at"]):
            cur["finished_at"] = r["finished_at"]
        if r["status"] == "failed" or (r["status"] == "running" and cur["status"] == "ok"):
            cur["status"] = r["status"]
    return rounds[::-1][:limit]


def _worker(conn: psycopg.Connection) -> dict[str, Any]:
    runs = _rows(conn, """
        SELECT run_id, step, status, started_at, finished_at, stats, left(error, 300) AS error,
               extract(epoch FROM finished_at - started_at)::float8 AS seconds
        FROM worker_runs WHERE step <> 'rag_sync' ORDER BY started_at DESC LIMIT %s""", (RECENT_WORKER_RUNS,))
    last = _rows(conn, """
        SELECT DISTINCT ON (step) step, status, started_at, finished_at
        FROM worker_runs ORDER BY step, started_at DESC""")
    day = _rows(conn, """
        SELECT count(*) FILTER (WHERE step = 'embed' AND status = 'ok') AS rounds_24h,
               count(*) FILTER (WHERE status = 'failed') AS failed_24h,
               coalesce(sum((stats->>'n_articles')::int) FILTER (WHERE step = 'embed'), 0) AS embedded_24h,
               coalesce(sum((stats->>'n_new_events')::int) FILTER (WHERE step = 'recluster'), 0) AS new_events_24h,
               coalesce(sum((stats->>'n_moved')::int) FILTER (WHERE step = 'recluster'), 0) AS moved_24h,
               coalesce(sum((stats->>'n_merged')::int) FILTER (WHERE step = 'recluster'), 0) AS merged_24h,
               coalesce(sum((stats->>'n_generated')::int) FILTER (WHERE step = 'name'), 0) AS named_24h
        FROM worker_runs WHERE started_at >= now() - interval '24 hours'""")[0]
    return {"last_by_step": last, "rounds": group_rounds(runs), **{k: int(v) for k, v in day.items()}}


def _events(conn: psycopg.Connection) -> dict[str, Any]:
    win = {"days": EVENT_WINDOW_DAYS}
    base = ("FROM events WHERE status NOT IN ('merged', 'hidden') "
            "AND last_seen >= now() - make_interval(days => %(days)s)")
    size_case = " ".join(
        f"WHEN size BETWEEN {lo} AND {hi} THEN {i}" if hi else f"WHEN size >= {lo} THEN {i}"
        for i, (lo, hi) in enumerate(SIZE_BUCKETS))
    by_size = {r["b"]: r for r in _rows(
        conn, f"SELECT CASE {size_case} END AS b, count(*) AS n, sum(size) AS articles {base} GROUP BY 1", win)}
    size_hist = [{"label": str(lo) if lo == hi else (f"{lo}–{hi}" if hi else f"≥ {lo}"),
                  "events": int(by_size.get(i, {}).get("n", 0)), "articles": int(by_size.get(i, {}).get("articles") or 0)}
                 for i, (lo, hi) in enumerate(SIZE_BUCKETS)]
    sources_hist = [{"n_sources": int(r["n_sources"]), "events": int(r["n"])}
                    for r in _rows(conn, f"SELECT n_sources, count(*) AS n {base} GROUP BY 1 ORDER BY 1", win)]
    naming = {r["name_source"]: int(r["n"]) for r in
              _rows(conn, f"SELECT name_source, count(*) AS n {base} AND size >= 2 GROUP BY 1", win)}
    categories = [{"category": r["c"], "events": int(r["n"]), "articles": int(r["a"])} for r in _rows(
        conn, f"SELECT coalesce(category_std, 'Chưa phân loại') AS c, count(*) AS n, sum(size) AS a {base} "
              "AND size >= 2 GROUP BY 1 ORDER BY 3 DESC LIMIT 12", win)]
    top = _rows(conn, f"""
        SELECT event_id, display_name, status, size, n_sources, sources, first_seen, last_seen, category_std,
               peak_score
        {base} AND last_seen >= now() - interval '24 hours'
        ORDER BY n_sources DESC, size DESC, last_seen DESC LIMIT %(top)s""", {**win, "top": TOP_EVENTS})
    multi = sum(r["events"] for r in sources_hist if r["n_sources"] >= 2)
    return {"window_days": EVENT_WINDOW_DAYS, "size_hist": size_hist, "sources_hist": sources_hist,
            "naming": naming, "categories": categories, "top": top,
            "total": sum(b["events"] for b in size_hist), "multi_source": multi}


def _tables(conn: psycopg.Connection) -> list[dict[str, Any]]:
    out = []
    for t in TABLES:
        n, size = conn.execute(f"SELECT (SELECT count(*) FROM {t}), pg_total_relation_size(%s::regclass)",
                               (t,)).fetchone()
        out.append({"table": t, "rows": int(n), "bytes": int(size)})
    return out


def _http_json(url: str, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:      # URL nội bộ (CRAWLER_URL), không phải URL người dùng
        return json.load(resp)


def crawler_job_items(jobs: dict[str, Any]) -> list[dict[str, Any]]:
    """`items` của `GET /crawl/jobs`, bỏ phần tử không phải object."""
    items = jobs.get("items")
    return [j for j in items if isinstance(j, dict)] if isinstance(items, list) else []


def format_crawler_job(j: dict[str, Any]) -> dict[str, Any]:
    """Một job của dịch vụ crawler (`GET /crawl/jobs`) → dạng gọn cho web (LiveCrawlerJob)."""
    per = []
    results = j.get("results")
    for src, r in sorted(results.items() if isinstance(results, dict) else []):
        if not isinstance(r, dict):
            continue
        dbr = r.get("db") if isinstance(r.get("db"), dict) else {}
        per.append({"source": src, "status": r.get("status"), "phase": r.get("phase"),
                    "discovered": r.get("discovered", 0), "processed": r.get("processed", 0),
                    "clean": r.get("clean", 0), "rejected": r.get("rejected", 0), "failed": r.get("failed", 0),
                    "inserted": dbr.get("inserted", 0), "updated": dbr.get("updated", 0),
                    "errors": [str(e)[:240] for e in (r.get("errors") or [])[:3]],
                    "n_errors": len(r.get("errors") or [])})
    return {"id": j.get("id"), "trigger": j.get("trigger"), "status": j.get("status"),
            "created_at": j.get("created_at"), "started_at": j.get("started_at"),
            "finished_at": j.get("finished_at"), "sources": per}


def crawler_status(base_url: str | None = None, timeout: float = 1.5) -> dict[str, Any] | None:
    """Lịch cào và vài job gần nhất từ dịch vụ crawler (:8002). Dịch vụ không chạy → None."""
    base = (base_url or os.environ.get("CRAWLER_URL") or "http://127.0.0.1:8002").rstrip("/")
    try:
        sched = _http_json(f"{base}/crawl/schedule", timeout)
        jobs = _http_json(f"{base}/crawl/jobs?limit={CRAWLER_JOBS}", timeout)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if not isinstance(sched, dict) or not isinstance(jobs, dict):       # crawler phiên bản khác/hỏng: coi như không có
        return None
    try:
        items = [format_crawler_job(j) for j in crawler_job_items(jobs)]
    except (AttributeError, TypeError, ValueError):
        return None
    interval, total, active = sched.get("interval_minutes"), jobs.get("total"), sched.get("active_job_id")
    return {"enabled": bool(sched.get("enabled")), "interval_minutes": interval if isinstance(interval, int) else None,
            "next_run_at": sched.get("next_run_at"), "active_job_id": active if isinstance(active, str) else None,
            "jobs_total": total if isinstance(total, int) else len(items), "jobs": items}


def live_overview(conn: psycopg.Connection, crawler: dict[str, Any] | None = None) -> dict[str, Any]:
    now = conn.execute("SELECT now()").fetchone()[0]
    return {"generated_at": now, "clock_mode": read_clock(conn).mode, "totals": _totals(conn),
            "sources": _sources(conn), "hourly": _hourly(conn, now), "daily": _daily(conn),
            "crawl_runs": _crawl_runs(conn), "worker": _worker(conn), "events": _events(conn),
            "tables": _tables(conn), "crawler": crawler}
