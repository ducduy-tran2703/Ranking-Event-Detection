"""Hợp đồng dữ liệu của API: hình dạng JSON mà frontend được phép tin vào.

Frontend React sinh kiểu TypeScript tự động từ các lớp này (qua /openapi.json).
Đổi một trường ở đây → chạy `make types` → frontend báo lỗi ở mọi chỗ dùng sai.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    rows: int
    loaded_at: datetime | None


class CategoryCount(BaseModel):
    source: str
    category: str | None
    n: int


class DateRange(BaseModel):
    min_date: str | None
    max_date: str | None


class Meta(BaseModel):
    dataset: str
    loaded_at: datetime | None
    load_seconds: float | None
    rows: int
    sources: list[str]
    categories: list[CategoryCount]
    date_range: DateRange


class OverviewTotal(BaseModel):
    articles: int
    sources: int
    categories: int
    days: int
    median_words: int | None


class SourceOverview(BaseModel):
    source: str
    articles: int
    categories: int
    first_published: str | None
    last_published: str | None
    active_days: int
    pct_missing_author: float
    pct_empty_content: float
    pct_short_content: float
    median_words: int | None


class Overview(BaseModel):
    total: OverviewTotal
    per_source: list[SourceOverview]


class ArticleSummary(BaseModel):
    article_id: str
    source: str
    category: str | None
    title: str | None
    sapo: str | None
    author: str | None
    published_at: str | None
    n_words: int
    url: str


class ArticlePage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ArticleSummary]


class ArticleDetail(BaseModel):
    article_id: str
    url: str
    source: str
    source_raw: str | None
    category: str | None
    title: str | None
    sapo: str | None
    author: str | None
    published_at: str | None
    published_at_raw: str | None
    n_words: int
    title_words: int
    content_text: str | None
    source_file: str | None
