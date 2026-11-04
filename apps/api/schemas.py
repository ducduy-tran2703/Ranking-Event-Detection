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


# ---------------------------------------------------------------- thống kê cho trang trực quan hoá
class TimelinePoint(BaseModel):
    bucket: str            # "YYYY-MM-DD" hoặc "YYYY-MM-DD HH:00", giờ Việt Nam
    source: str
    n: int


class HourPoint(BaseModel):
    hour: int              # 0–23, giờ Việt Nam
    source: str
    n: int


class IssueCounts(BaseModel):
    source: str
    articles: int
    missing_author: int
    empty_content: int
    short_content: int
    bad_date: int
    future_date: int
    duplicate_url: int
    duplicate_id: int


class RawSourceValue(BaseModel):
    source_raw: str | None
    source: str
    folder: str | None      # tên thư mục trên kho: silver/<folder>/<tên file>
    n: int


class WordsBin(BaseModel):
    source: str
    bin: int               # 0, 100, 200, … 2000 (2000 = từ 2000 trở lên)
    n: int


class TitleWordsBin(BaseModel):
    source: str
    words: int             # 1–40 (40 = từ 40 trở lên)
    n: int


class DuplicateTitle(BaseModel):
    title: str | None
    n: int
    sources: int
    source_list: list[str]


class Quality(BaseModel):
    short_content_words: int
    issues_per_source: list[IssueCounts]
    raw_source_values: list[RawSourceValue]
    words_histogram: list[WordsBin]
    title_words_histogram: list[TitleWordsBin]
    duplicate_titles: list[DuplicateTitle]


class FileInfo(BaseModel):
    key: str
    size_bytes: int
    last_modified: datetime


class ReloadResult(BaseModel):
    rows: int
    seconds: float
    loaded_at: datetime


class Freshness(BaseModel):
    loaded_at: datetime | None
    remote_latest_modified: datetime | None
    has_newer_data: bool          # trên kho có file sửa SAU lần nạp gần nhất
    newer_files: list[str]
    checked_at: datetime


# ---------------------------------------------------------------- sự kiện (kết quả pipeline, data/runs/<run_id>/)
# nguon_ten: model (ViT5) | medoid (rơi về tiêu đề bài đại diện) | title (sự kiện 1 bài) | an (tên đang ẩn — cửa sổ tập
# test đặt tên; `ten` khi đó là tiêu đề bài đại diện, tên mô hình KHÔNG được trả ra ở bất kỳ đâu).
class HideWindow(BaseModel):
    tu_ngay: str
    den_ngay: str


class RunInfo(BaseModel):
    run_id: str
    versions: dict[str, str]
    loaded_at: datetime
    load_seconds: float
    n_su_kien: int
    n_su_kien_nhieu_bai: int
    n_bai: int
    nguon_bao: list[str]
    du_lieu_tu: str | None     # bài sớm nhất / muộn nhất của run (giờ VN)
    du_lieu_den: str | None
    pham_vi_tu: str | None     # giới hạn --start/--end của lần chạy (None = cả kho)
    pham_vi_den: str | None
    xu_huong_tu: str
    xu_huong_den: str
    cua_so_an_ten: HideWindow | None
    n_su_kien_bi_an: int
    ghi_chu: list[str]


class TrendTimes(BaseModel):
    dau: str               # mốc đầu (giờ VN); mốc thứ i = dau + i · buoc_gio
    cuoi: str
    buoc_gio: float
    so_moc: int
    mac_dinh: str          # mốc cuối có ≥ 10 sự kiện trên bảng
    so_su_kien: list[int]  # số sự kiện trên bảng ở từng mốc


class TrendItem(BaseModel):
    hang: int
    event_id: str
    ten: str
    nguon_ten: str
    ten_bi_an: bool
    score: float
    so_bai_den_t: int
    so_bai_3h: int
    so_bao: int
    n_nguon_hd: float
    van_toc: float
    tuoi_gio: float


class Trending(BaseModel):
    t: str
    t_truoc: str | None
    t_sau: str | None
    mac_dinh: str
    items: list[TrendItem]


class SourceCount(BaseModel):
    source: str
    n: int


class EventSummary(BaseModel):
    event_id: str
    ten: str
    nguon_ten: str
    ten_bi_an: bool
    size: int
    n_sources: int
    sources: list[SourceCount]
    first_seen: str
    last_seen: str
    medoid_title: str
    tong_diem: float | None
    diem_cao_nhat: float | None
    luc_cao_nhat: str | None
    so_gio_trong_top10: int


class EventPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[EventSummary]


class EventArticle(BaseModel):
    article_id: str
    title: str
    source: str
    category: str | None
    published_at: str
    is_medoid: bool
    url: str | None


class EventPoint(BaseModel):
    t: str                 # mốc giờ (giờ VN)
    so_bai: int            # số bài đăng trong (t − 1 giờ, t]
    so_bai_den_t: int
    diem: float            # điểm xu hướng tính lại tại t; 0 khi không là ứng viên
    ung_vien: bool
    hang: int | None       # hạng trên bảng top-20 tại t (None: ngoài bảng)


class CategoryN(BaseModel):
    category: str
    n: int


class EventDetail(EventSummary):
    chuyen_muc: list[CategoryN]
    bai: list[EventArticle]
    chuoi: list[EventPoint]
    chuoi_bi_cat: bool
