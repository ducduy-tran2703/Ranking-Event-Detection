"""Đọc lớp Silver (JSONL trên R2 hoặc thư mục cục bộ) vào DuckDB và trả về thống kê.

Chỉ đọc. Không có hàm nào ghi hay xoá dữ liệu trên kho.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from eventrank.common.config import LakeConfig

COLUMNS = {
    "article_id": "VARCHAR", "url": "VARCHAR", "source": "VARCHAR", "category": "VARCHAR",
    "title": "VARCHAR", "sapo": "VARCHAR", "author": "VARCHAR",
    "published_at": "VARCHAR", "content_text": "VARCHAR",
}
SHORT_CONTENT_WORDS = 80
ISSUES = {
    "missing_author": "author IS NULL",
    "empty_content": "n_words = 0",
    "short_content": f"n_words BETWEEN 1 AND {SHORT_CONTENT_WORDS - 1}",
    "bad_date": "published_at IS NULL",
    "future_date": "published_at > now() + INTERVAL 1 HOUR",
    "duplicate_url": "url IN (SELECT url FROM articles GROUP BY url HAVING count(*) > 1)",
    "duplicate_id": "article_id IN (SELECT article_id FROM articles GROUP BY article_id"
                    " HAVING count(*) > 1)",
}
SORTS = {"newest": "published_at DESC NULLS LAST", "oldest": "published_at ASC NULLS LAST",
         "longest": "n_words DESC", "shortest": "n_words ASC"}


@dataclass
class Filters:
    source: str | None = None
    category: str | None = None
    q: str | None = None
    date_from: str | None = None      # YYYY-MM-DD, giờ Việt Nam
    date_to: str | None = None        # YYYY-MM-DD, tính cả ngày này
    issue: str | None = None

    def where(self) -> tuple[str, list[Any]]:
        parts, params = [], []
        if self.source:
            parts.append("source = ?"); params.append(self.source.lower())
        if self.category:
            parts.append("category = ?"); params.append(self.category)
        if self.q:
            parts.append("(title ILIKE ? OR sapo ILIKE ?)"); params += [f"%{self.q}%"] * 2
        if self.date_from:
            parts.append("published_at >= CAST(? AS DATE)"); params.append(self.date_from)
        if self.date_to:
            parts.append("published_at < CAST(? AS DATE) + INTERVAL 1 DAY")
            params.append(self.date_to)
        if self.issue:
            if self.issue not in ISSUES:
                raise ValueError(f"issue không hợp lệ: {self.issue}")
            parts.append(ISSUES[self.issue])
        return (" WHERE " + " AND ".join(parts)) if parts else "", params


def _rows(cur: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


class SilverStore:
    def __init__(self, cfg: LakeConfig):
        self.cfg = cfg
        self._con = duckdb.connect()
        self._lock = threading.Lock()
        self.loaded_at: datetime | None = None
        self.load_seconds: float | None = None
        # GLOBAL: mỗi cursor() là một phiên mới, thiết lập mức phiên sẽ không được kế thừa
        # và cursor sẽ quay về UTC — bài đăng 0h–7h sáng bị xếp nhầm sang ngày hôm trước.
        self._con.execute("SET GLOBAL TimeZone = 'Asia/Ho_Chi_Minh'")
        if cfg.backend == "r2":
            self._con.execute("INSTALL httpfs; LOAD httpfs;")
            self._create_secret()

    def _create_secret(self) -> None:
        # CREATE SECRET không nhận tham số chuẩn bị sẵn; thoát dấu nháy để an toàn.
        def q(v: str | None) -> str:
            return "'" + (v or "").replace("'", "''") + "'"
        self._con.execute(
            f"CREATE OR REPLACE SECRET lake (TYPE r2, KEY_ID {q(self.cfg.access_key_id)}, "
            f"SECRET {q(self.cfg.secret_access_key)}, ACCOUNT_ID {q(self.cfg.account_id)})"
        )

    # ------------------------------------------------------------------ nạp dữ liệu
    def reload(self) -> dict[str, Any]:
        uri = self.cfg.silver_uri.replace("'", "''")
        cols = ", ".join(f"{k}: '{v}'" for k, v in COLUMNS.items())
        started = datetime.now(UTC)
        with self._lock:
            self._con.execute(f"""
                CREATE OR REPLACE TABLE articles AS
                SELECT
                    article_id,
                    url,
                    lower(trim(source))                          AS source,
                    source                                       AS source_raw,
                    trim(category)                               AS category,
                    title,
                    sapo,
                    NULLIF(trim(author), '')                     AS author,
                    TRY_CAST(published_at AS TIMESTAMPTZ)        AS published_at,
                    published_at                                 AS published_at_raw,
                    content_text,
                    CASE WHEN content_text IS NULL OR trim(content_text) = '' THEN 0
                         ELSE len(string_split(regexp_replace(trim(content_text), '\\s+', ' ', 'g'), ' '))
                    END                                          AS n_words,
                    len(string_split(regexp_replace(trim(coalesce(title, '')), '\\s+', ' ', 'g'), ' '))
                                                                 AS title_words,
                    filename                                     AS source_file
                FROM read_json('{uri}', format = 'newline_delimited', filename = true,
                               columns = {{{cols}}})
            """)
            self.loaded_at = datetime.now(UTC)
            self.load_seconds = (self.loaded_at - started).total_seconds()
        return {"rows": self.count(), "seconds": round(self.load_seconds, 2)}

    def _q(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self._con.cursor()          # mỗi lời gọi một cursor: an toàn đa luồng
        try:
            cur.execute(sql, params or [])
            return _rows(cur)
        finally:
            cur.close()

    def count(self) -> int:
        return self._q("SELECT count(*) AS n FROM articles")[0]["n"]

    # ------------------------------------------------------------------ thông tin chung
    def list_files(self) -> list[dict[str, Any]]:
        """Danh sách file nguồn kèm dung lượng và thời điểm sửa — để biết dữ liệu mới tới đâu."""
        if self.cfg.backend == "local":
            root = Path(self.cfg.local_root)
            return [{"key": str(p.relative_to(root)), "size_bytes": p.stat().st_size,
                     "last_modified": datetime.fromtimestamp(p.stat().st_mtime, UTC)}
                    for p in sorted(root.glob(self.cfg.silver_glob))]
        import boto3
        s3 = boto3.client("s3", endpoint_url=f"https://{self.cfg.account_id}.r2.cloudflarestorage.com",
                          aws_access_key_id=self.cfg.access_key_id,
                          aws_secret_access_key=self.cfg.secret_access_key, region_name="auto")
        prefix = self.cfg.silver_glob.split("*", 1)[0]
        out = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=self.cfg.bucket,
                                                                  Prefix=prefix):
            for o in page.get("Contents", []):
                out.append({"key": o["Key"], "size_bytes": o["Size"],
                            "last_modified": o["LastModified"]})
        return out

    def meta(self) -> dict[str, Any]:
        return {
            "dataset": self.cfg.describe(),
            "loaded_at": self.loaded_at,
            "load_seconds": self.load_seconds,
            "rows": self.count(),
            "sources": [r["source"] for r in self._q(
                "SELECT source FROM articles GROUP BY 1 ORDER BY count(*) DESC")],
            "categories": self._q(
                "SELECT source, category, count(*) AS n FROM articles GROUP BY 1, 2 ORDER BY 1, 3 DESC"),
            "date_range": self._q(
                "SELECT strftime(min(published_at), '%Y-%m-%d') AS min_date,"
                " strftime(max(published_at), '%Y-%m-%d') AS max_date FROM articles")[0],
        }

    # ------------------------------------------------------------------ thống kê
    def overview(self) -> dict[str, Any]:
        per_source = self._q(f"""
            SELECT source,
                   count(*)                                                AS articles,
                   count(DISTINCT category)                                AS categories,
                   strftime(min(published_at), '%Y-%m-%d %H:%M')           AS first_published,
                   strftime(max(published_at), '%Y-%m-%d %H:%M')           AS last_published,
                   count(DISTINCT CAST(published_at AS DATE))              AS active_days,
                   round(100.0 * count(*) FILTER (WHERE author IS NULL) / count(*), 1)
                                                                           AS pct_missing_author,
                   round(100.0 * count(*) FILTER (WHERE n_words = 0) / count(*), 1)
                                                                           AS pct_empty_content,
                   round(100.0 * count(*) FILTER (WHERE n_words BETWEEN 1 AND {SHORT_CONTENT_WORDS - 1})
                         / count(*), 1)                                    AS pct_short_content,
                   CAST(median(n_words) AS INTEGER)                        AS median_words
            FROM articles GROUP BY source ORDER BY articles DESC
        """)
        total = self._q("""
            SELECT count(*) AS articles, count(DISTINCT source) AS sources,
                   count(DISTINCT category) AS categories,
                   count(DISTINCT CAST(published_at AS DATE)) AS days,
                   CAST(median(n_words) AS INTEGER) AS median_words
            FROM articles
        """)[0]
        return {"total": total, "per_source": per_source}

    def timeline(self, f: Filters, granularity: str = "day") -> list[dict[str, Any]]:
        fmt = {"day": "%Y-%m-%d", "hour": "%Y-%m-%d %H:00"}.get(granularity)
        if fmt is None:
            raise ValueError("granularity phải là 'day' hoặc 'hour'")
        where, params = f.where()
        return self._q(f"""
            SELECT strftime(date_trunc('{granularity}', published_at), '{fmt}') AS bucket,
                   source, count(*) AS n
            FROM articles {where} {'AND' if where else 'WHERE'} published_at IS NOT NULL
            GROUP BY 1, 2 ORDER BY 1, 2
        """, params)

    def hour_of_day(self, f: Filters) -> list[dict[str, Any]]:
        where, params = f.where()
        return self._q(f"""
            SELECT hour(published_at) AS hour, source, count(*) AS n
            FROM articles {where} {'AND' if where else 'WHERE'} published_at IS NOT NULL
            GROUP BY 1, 2 ORDER BY 1, 2
        """, params)

    def categories(self, f: Filters) -> list[dict[str, Any]]:
        where, params = f.where()
        return self._q(f"""
            SELECT source, category, count(*) AS n
            FROM articles {where} GROUP BY 1, 2 ORDER BY n DESC
        """, params)

    def quality(self) -> dict[str, Any]:
        issue_cols = ",\n".join(
            f"count(*) FILTER (WHERE {cond}) AS {name}" for name, cond in ISSUES.items())
        per_source = self._q(f"SELECT source, count(*) AS articles, {issue_cols} "
                             "FROM articles GROUP BY source ORDER BY articles DESC")
        return {
            "short_content_words": SHORT_CONTENT_WORDS,
            "issues_per_source": per_source,
            "raw_source_values": self._q(
                "SELECT source_raw, source, count(*) AS n FROM articles GROUP BY 1, 2 ORDER BY 3 DESC"),
            "words_histogram": self._q("""
                SELECT source, least(n_words // 100, 20) * 100 AS bin, count(*) AS n
                FROM articles GROUP BY 1, 2 ORDER BY 2, 1"""),
            "title_words_histogram": self._q("""
                SELECT source, least(title_words, 40) AS words, count(*) AS n
                FROM articles GROUP BY 1, 2 ORDER BY 2, 1"""),
            "duplicate_titles": self._q("""
                SELECT title, count(*) AS n, count(DISTINCT source) AS sources,
                       list(DISTINCT source) AS source_list
                FROM articles GROUP BY title HAVING count(*) > 1
                ORDER BY n DESC LIMIT 20"""),
        }

    # ------------------------------------------------------------------ duyệt bài
    def list_articles(self, f: Filters, page: int = 1, page_size: int = 50,
                      sort: str = "newest") -> dict[str, Any]:
        order = SORTS.get(sort)
        if order is None:
            raise ValueError(f"sort không hợp lệ: {sort}")
        page_size = max(1, min(page_size, 200))
        page = max(1, page)
        where, params = f.where()
        total = self._q(f"SELECT count(*) AS n FROM articles {where}", params)[0]["n"]
        items = self._q(f"""
            SELECT article_id, source, category, title, left(sapo, 220) AS sapo, author,
                   strftime(published_at, '%Y-%m-%d %H:%M') AS published_at, n_words, url
            FROM articles {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """, params + [page_size, (page - 1) * page_size])
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    def get_article(self, article_id: str) -> dict[str, Any] | None:
        rows = self._q("""
            SELECT article_id, url, source, source_raw, category, title, sapo, author,
                   strftime(published_at, '%Y-%m-%d %H:%M:%S') AS published_at,
                   published_at_raw, n_words, title_words, content_text, source_file
            FROM articles WHERE article_id = ? LIMIT 1
        """, [article_id])
        return rows[0] if rows else None
