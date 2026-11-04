"""Giao diện crawler + `run_crawler` (chạy một crawler một lần, ghi `crawl_runs`, validate, upsert).

Người viết crawler CHỈ cần viết một lớp có:

    class TuoiTreRss:
        source = "tuoitre"              # phải có trong configs/sources.yaml
        name = "tuoitre_rss"            # → articles.ingested_via = "crawler:tuoitre_rss"
        parser_version = "tuoitre-rss-1"   # đổi cách tách bài → tăng phiên bản (mục 3.2)

        def crawl(self, ctx: CrawlContext) -> Iterable[dict]:
            xml = ctx.client.get_xml("https://…/rss.xml")
            for url in …:
                html = ctx.client.get(url).text
                yield {"url": url, "source": "tuoitre", "category": …, "title": …, "sapo": …,
                       "author": … or None, "published_at": "2026-09-16T07:07:00+07:00",
                       "content_text": …}

rồi đăng ký `crawler: eventrank.ingest.crawlers.tuoitre:TuoiTreRss` trong configs/sources.yaml. Mọi
việc còn lại (giãn cách, robots, chuẩn hoá NFC, kiểm hợp đồng, ghi DB idempotent, ghi nhật ký lần
chạy) do khung lo. Crawler KHÔNG import psycopg, KHÔNG tự ghi DB/R2, KHÔNG tự tạo httpx.Client —
mọi request qua `ctx.client` (PoliteClient). Bài lỗi cứ yield: khung loại và đếm lý do, lô không
dừng.

Trạng thái lần chạy (`crawl_runs.status`): `ok`; `failed` (crawler ném lỗi — phần đã cào VẪN được
lưu); `blocked` (báo chặn: DomainBlocked/RobotsDisallowed → dừng, báo người dùng, không vượt chặn).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import psycopg

from eventrank.ingest import sink
from eventrank.ingest.contract import Article, Rejected, validate_article
from eventrank.ingest.fetch import DomainBlocked, PoliteClient, RobotsDisallowed
from eventrank.ingest.sink import UpsertResult


class CrawlerError(RuntimeError):
    pass


@dataclass
class CrawlContext:
    """Những gì một crawler được dùng trong một lần chạy."""
    client: PoliteClient | None      # mọi request tới báo đi qua đây
    now: datetime                    # "bây giờ" của lần chạy (có múi giờ)
    source: str
    # lúc lần chạy THÀNH CÔNG trước của crawler này kết thúc (cào tăng dần); None = lần đầu
    since: datetime | None = None
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("eventrank.crawler"))


@runtime_checkable
class Crawler(Protocol):
    source: str
    name: str
    parser_version: str

    def crawl(self, ctx: CrawlContext) -> Iterable[Mapping[str, Any]]: ...


@dataclass
class RunResult:
    run_id: int
    status: str
    counts: UpsertResult
    n_seen: int
    error: str | None = None


def _update_run(conn: psycopg.Connection, run_id: int, n_seen: int, c: UpsertResult,
                status: str | None = None, error: str | None = None) -> None:
    conn.execute("""
        UPDATE crawl_runs SET n_seen = %s, n_new = %s, n_updated = %s, n_unchanged = %s,
               n_rejected = %s, reject_reasons = %s::jsonb,
               status = coalesce(%s, status), error = coalesce(%s, error),
               finished_at = CASE WHEN %s::text IS NULL THEN finished_at ELSE now() END
        WHERE run_id = %s""",
        (n_seen, c.inserted, c.updated, c.unchanged, c.rejected,
         json.dumps(dict(c.reject_reasons)), status, error, status, run_id))


def run_crawler(conn: psycopg.Connection, crawler: Crawler, client: PoliteClient | None, *,
                now: datetime | None = None, batch_size: int = 100,
                max_articles: int | None = None,
                logger: logging.Logger | None = None) -> RunResult:
    """Chạy `crawler.crawl()` một lần. Không ném lỗi của crawler ra ngoài (trừ Ctrl+C): ghi vào
    `crawl_runs` và trả `RunResult.status` — vòng `--loop` chạy tiếp lần sau.
    `max_articles`: dừng sau N bài (lát cắt thử 12 bài, skill add-news-source bước 2)."""
    log = logger or logging.getLogger(f"eventrank.crawler.{crawler.name}")
    now = now or datetime.now(UTC)
    known = sink.known_sources(conn)
    if crawler.source not in known:
        raise CrawlerError(f"Nguồn {crawler.source!r} chưa có trong bảng sources — thêm vào "
                           "configs/sources.yaml rồi chạy `ingest sources sync`")
    since = conn.execute(
        "SELECT max(finished_at) FROM crawl_runs WHERE source = %s AND crawler = %s "
        "AND status = 'ok'", (crawler.source, crawler.name)).fetchone()[0]
    run_id = conn.execute(
        "INSERT INTO crawl_runs (source, crawler, parser_version) VALUES (%s, %s, %s) "
        "RETURNING run_id", (crawler.source, crawler.name, crawler.parser_version)).fetchone()[0]
    ctx = CrawlContext(client=client, now=now, source=crawler.source, since=since, log=log)
    via = f"crawler:{crawler.name}"
    counts, n_seen, buf = UpsertResult(), 0, []
    status, error = "ok", None

    def flush() -> None:
        nonlocal buf
        counts.add(sink.upsert_articles(conn, buf, via, parser_version=crawler.parser_version,
                                        batch_size=batch_size))
        buf = []
        _update_run(conn, run_id, n_seen, counts)

    try:
        for raw in crawler.crawl(ctx):
            n_seen += 1
            res: Article | Rejected = validate_article(raw, known_sources=known, now=now,
                                                       expected_source=crawler.source)
            if isinstance(res, Rejected):
                log.info("loại %s: %s", res.ref, "; ".join(res.errors))
            buf.append(res)
            if len(buf) >= batch_size:
                flush()
            if max_articles is not None and n_seen >= max_articles:
                break                            # đóng generator: crawler không tải thêm
    except (DomainBlocked, RobotsDisallowed) as e:
        status, error = "blocked", f"{e.__class__.__name__}: {e}"
        log.error("BÁO CHẶN — dừng, báo người dùng, không vượt chặn: %s", e)
    except KeyboardInterrupt:
        flush()
        _update_run(conn, run_id, n_seen, counts, "failed", "bị dừng tay (Ctrl+C)")
        raise
    except Exception as e:      # ghi lỗi của crawler vào crawl_runs, không làm sập vòng --loop
        status, error = "failed", f"{e.__class__.__name__}: {e}"[:2000]
        log.exception("crawler %s lỗi", crawler.name)
    flush()
    _update_run(conn, run_id, n_seen, counts, status, error)
    return RunResult(run_id, status, counts, n_seen, error)
