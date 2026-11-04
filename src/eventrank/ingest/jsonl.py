"""Nạp Silver JSONL có sẵn (data/lake/silver/*/*.jsonl, hoặc file do script riêng của một thành viên
xuất ra) vào Postgres, qua đúng hợp đồng như crawler.

Đây cũng là đường cho người muốn giữ script cào riêng: chỉ cần xuất JSONL đúng mục 5.3 rồi
`python -m eventrank.ingest import-jsonl '<glob>'` — idempotent, chạy lại không tạo bản mới.

Mỗi nguồn có bài trong lần nhập được ghi một dòng `crawl_runs` (crawler = `import_jsonl`) để
`ingest status` thấy cả nguồn nhập bằng JSONL. Dòng JSON hỏng → bị loại với mã `json_invalid`.
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from eventrank.ingest import sink
from eventrank.ingest.contract import Article, Rejected, validate_article
from eventrank.ingest.sink import UpsertResult

VIA = "import_jsonl"


def expand(patterns: Iterable[str]) -> list[str]:
    files: list[str] = []
    for pat in patterns:
        hit = sorted(glob.glob(pat)) if any(c in pat for c in "*?[") else [pat]
        files += [f for f in hit if Path(f).is_file()]
    if not files:
        raise FileNotFoundError(f"Không có file nào khớp: {', '.join(patterns)}")
    return files


def read_jsonl(patterns: Iterable[str]) -> Iterator[Any | Rejected]:
    """Mỗi dòng không trống → giá trị JSON (thường là dict) hoặc `Rejected` (json_invalid)."""
    for path in expand(patterns):
        with open(path, encoding="utf-8-sig") as f:     # -sig: bỏ BOM nếu có
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    yield Rejected(f"{path}:{lineno}", (f"json_invalid: {e.msg}",))


def _source_of(raw: Any, known: set[str]) -> str | None:
    if isinstance(raw, dict):
        s = str(raw.get("source") or "").strip().lower()
        return s if s in known else None
    return None


def import_jsonl(conn: psycopg.Connection, patterns: Iterable[str], *, now: datetime | None = None,
                 batch_size: int = 1000) -> UpsertResult:
    now = now or datetime.now(UTC)
    started = datetime.now(UTC)
    known = sink.known_sources(conn)
    per_source: dict[str, UpsertResult] = defaultdict(UpsertResult)
    seen: dict[str, int] = defaultdict(int)
    buffers: dict[str, list[Article | Rejected]] = defaultdict(list)
    total = UpsertResult()

    def flush(src: str) -> None:
        if buffers[src]:
            per_source[src].add(sink.upsert_articles(conn, buffers[src], VIA,
                                                     batch_size=batch_size))
            buffers[src] = []

    for raw in read_jsonl(patterns):
        res = raw if isinstance(raw, Rejected) else validate_article(raw, known_sources=known,
                                                                     now=now)
        src = _source_of(raw, known)
        if src is None:                          # không gán được cho nguồn nào: chỉ đếm tổng
            total.add(sink.upsert_articles(conn, [res], VIA))
            continue
        seen[src] += 1
        buffers[src].append(res)
        if len(buffers[src]) >= batch_size:
            flush(src)
    for src in list(buffers):
        flush(src)
    for src, c in sorted(per_source.items()):
        total.add(c)
        conn.execute("""
            INSERT INTO crawl_runs (source, crawler, started_at, finished_at, status, n_seen, n_new,
                                    n_updated, n_unchanged, n_rejected, reject_reasons)
            VALUES (%s, %s, %s, now(), 'ok', %s, %s, %s, %s, %s, %s::jsonb)""",
            (src, VIA, started, seen[src], c.inserted, c.updated, c.unchanged, c.rejected,
             json.dumps(dict(c.reject_reasons))))
    return total
