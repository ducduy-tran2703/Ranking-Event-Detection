"""Ghi bài đã qua hợp đồng vào Postgres (bảng `articles`, `sources` — migration 001_ingest.sql).

Idempotent (mục 6.1): khoá `article_id = sha256(url)`, `INSERT … ON CONFLICT (article_id)`. Cào lại
một bài:
- nội dung không đổi (cùng `content_hash`) → KHÔNG ghi gì (đếm `unchanged`) — chạy lại một lô =
  0 bản mới, 0 cập nhật; `updated_at` không nhảy nên worker giai đoạn 2 không xử lý lại vô ích;
- nội dung đổi (bài sửa sau khi đăng, parser mới) → cập nhật mọi trường nội dung, `quality_flags`,
  `ingested_via`, `parser_version`, `updated_at`; GIỮ `crawled_at` lần đầu (biết bài vào hệ thống
  lúc nào).
Bài `Rejected` chỉ được đếm (kèm mã lý do), không ghi.

Mỗi lô một transaction: lỗi giữa chừng mất tối đa một lô, chạy lại an toàn vì idempotent.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import psycopg

from eventrank.ingest.contract import Article, Rejected

_UPSERT = """
INSERT INTO articles (article_id, url, source, category, title, sapo, author, published_at,
                      content_text, ingested_via, parser_version, content_hash, quality_flags)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (article_id) DO UPDATE SET
    category = EXCLUDED.category, title = EXCLUDED.title, sapo = EXCLUDED.sapo,
    author = EXCLUDED.author, published_at = EXCLUDED.published_at,
    content_text = EXCLUDED.content_text, ingested_via = EXCLUDED.ingested_via,
    parser_version = EXCLUDED.parser_version, content_hash = EXCLUDED.content_hash,
    quality_flags = EXCLUDED.quality_flags, updated_at = now()
WHERE articles.content_hash <> EXCLUDED.content_hash
RETURNING (xmax = 0) AS inserted
"""
# xmax = 0 ⇔ dòng vừa được INSERT (dòng UPDATE mang xmax của transaction). Dòng không đổi bị WHERE
# loại khỏi UPDATE nên không có trong RETURNING → đếm là unchanged.


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    reject_reasons: Counter = field(default_factory=Counter)

    @property
    def seen(self) -> int:
        return self.inserted + self.updated + self.unchanged + self.rejected

    def add(self, other: UpsertResult) -> UpsertResult:
        self.inserted += other.inserted
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.rejected += other.rejected
        self.reject_reasons.update(other.reject_reasons)
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"inserted": self.inserted, "updated": self.updated, "unchanged": self.unchanged,
                "rejected": self.rejected, "reject_reasons": dict(self.reject_reasons)}


def _write_batch(conn: psycopg.Connection, batch: list[Article], via: str,
                 parser_version: str | None) -> UpsertResult:
    res = UpsertResult()
    if not batch:
        return res
    params = [(a.article_id, a.url, a.source, a.category, a.title, a.sapo, a.author,
               a.published_at, a.content_text, via, parser_version, a.content_hash,
               list(a.quality_flags)) for a in batch]
    with conn.transaction(), conn.cursor() as cur:
        # Mỗi bài một câu lệnh (executemany, gửi theo pipeline): hai bản của cùng một bài trong
        # một lô không gây lỗi "ON CONFLICT … cannot affect row a second time".
        cur.executemany(_UPSERT, params, returning=True)
        while True:
            row = cur.fetchone()
            if row is None:
                res.unchanged += 1
            elif row[0]:
                res.inserted += 1
            else:
                res.updated += 1
            if not cur.nextset():
                break
    return res


def upsert_articles(conn: psycopg.Connection, items: Iterable[Article | Rejected], via: str, *,
                    parser_version: str | None = None, batch_size: int = 500) -> UpsertResult:
    """Ghi theo lô; trả số bài inserted/updated/unchanged/rejected (+ đếm mã lý do loại).
    `via`: `import_jsonl` | `replay` | `crawler:<tên>` — ghi vào cột `ingested_via`."""
    total = UpsertResult()
    batch: list[Article] = []
    for it in items:
        if isinstance(it, Rejected):
            total.rejected += 1
            total.reject_reasons.update(it.codes)
            continue
        batch.append(it)
        if len(batch) >= batch_size:
            total.add(_write_batch(conn, batch, via, parser_version))
            batch = []
    total.add(_write_batch(conn, batch, via, parser_version))
    return total


# ---------------------------------------------------------------------- nguồn tin
_SOURCE_COLS = ("source", "display_name", "homepage", "enabled", "crawler", "notes")


def sync_sources(conn: psycopg.Connection, rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Đưa danh sách nguồn (configs/sources.yaml) vào bảng `sources`. Chỉ thêm/sửa, KHÔNG xoá nguồn
    vắng mặt (bài cũ còn tham chiếu tới nó)."""
    sql = f"""
        INSERT INTO sources ({", ".join(_SOURCE_COLS)}) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source) DO UPDATE SET
            display_name = EXCLUDED.display_name, homepage = EXCLUDED.homepage,
            enabled = EXCLUDED.enabled, crawler = EXCLUDED.crawler, notes = EXCLUDED.notes,
            updated_at = now()
        WHERE (sources.display_name, sources.homepage, sources.enabled, sources.crawler,
               sources.notes)
              IS DISTINCT FROM (EXCLUDED.display_name, EXCLUDED.homepage, EXCLUDED.enabled,
                                EXCLUDED.crawler, EXCLUDED.notes)
        RETURNING (xmax = 0)"""
    out = {"inserted": 0, "updated": 0, "unchanged": 0}
    with conn.transaction(), conn.cursor() as cur:
        for r in rows:
            src = str(r["source"]).strip().lower()
            cur.execute(sql, (src, r.get("display_name") or src,
                              r.get("homepage") or None, bool(r.get("enabled", False)),
                              r.get("crawler") or None, r.get("notes") or None))
            row = cur.fetchone()
            key = "unchanged" if row is None else ("inserted" if row[0] else "updated")
            out[key] += 1
    return out


def known_sources(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT source FROM sources")}
