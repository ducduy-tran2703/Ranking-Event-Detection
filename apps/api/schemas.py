"""Hợp đồng dữ liệu của API: hình dạng JSON mà frontend được phép tin vào.

Frontend React sinh kiểu TypeScript tự động từ các lớp này (qua /openapi.json).
Đổi một trường ở đây → chạy `make types` → frontend báo lỗi ở mọi chỗ dùng sai.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RAGQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=2048)
    source: str | None = Field(default=None, min_length=1, max_length=64)
    date_from: date | None = None
    date_to: date | None = None
    max_tokens: int = Field(default=1024, ge=1, le=1024)
    allow_fallback: bool = False

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('date_from phải <= date_to')
        return self


class RAGSnapshot(BaseModel):
    from_date: str | None
    to_date: str | None
    articles: int
    sources: list[str]


class RAGSource(BaseModel):
    """Nguồn đã kiểm. kind='chunk': đoạn bài báo (URL/offset từ DB). kind='data': câu dữ liệu tool SQL
    sinh tất định (số bài, phạm vi kho, sự kiện) — không có URL; `text` là câu gốc được trích."""
    citation_id: int
    kind: Literal['chunk', 'data'] = 'chunk'
    chunk_id: str | None = None
    article_id: str | None = None
    title: str
    url: str | None = None
    source: str | None = None
    published_at: datetime | None = None
    start_char: int | None = None
    end_char: int | None = None
    chunking_version: str | None = None
    tool: str | None = None
    text: str | None = None
    quotes: list[str]


class RAGAnswer(BaseModel):
    status: Literal['answered', 'insufficient_evidence', 'unsupported_query', 'invalid_generation', 'smalltalk']
    answer: str
    sources: list[RAGSource]
    retrieval_mode: Literal['hybrid', 'bm25_only', 'dense_only'] | None
    degraded: bool
    snapshot: RAGSnapshot
    trace: dict[str, Any]


# ---------------------------------------------------------------------- khung chat hỏi đáp (migration 008)
RAGChatStatusValue = Literal['queued', 'running', 'answered', 'insufficient_evidence', 'unsupported_query',
                             'invalid_generation', 'smalltalk', 'failed', 'cancelled']


class RAGChatAsk(BaseModel):
    """Một câu hỏi gửi vào hàng đợi. `conversation_id` rỗng → tạo cuộc trò chuyện mới."""
    model_config = ConfigDict(extra='forbid')
    conversation_id: int | None = Field(default=None, ge=1)
    question: str = Field(min_length=1, max_length=2048)
    source: str | None = Field(default=None, min_length=1, max_length=64)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('date_from phải <= date_to')
        return self


class RAGChatFilters(BaseModel):
    source: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class RAGChatSource(RAGSource):
    event_id: str | None = None
    event_name: str | None = None


class RAGChatMessage(BaseModel):
    message_id: int
    conversation_id: int
    question: str
    filters: RAGChatFilters
    status: RAGChatStatusValue
    answer: str | None
    sources: list[RAGChatSource]
    retrieval_mode: Literal['hybrid', 'bm25_only', 'dense_only'] | None
    degraded: bool | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    seconds: float | None
    queue_position: int | None


class RAGConversation(BaseModel):
    conversation_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    n_messages: int
    last_status: RAGChatStatusValue | None


class RAGConversationDetail(BaseModel):
    conversation: RAGConversation
    messages: list[RAGChatMessage]


class RAGChatStatus(BaseModel):
    """Trạng thái hỏi đáp cho web: có dùng được không (kiểm nhanh, không gọi GPU) và hạn mức của người đang đăng nhập."""
    available: bool
    problems: list[str]
    snapshot: RAGSnapshot | None
    daily_limit: int | None
    used_today: int | None
    # False khi bật tool calling (configs/rag.yaml → tool_calling.enabled): chatbot nhớ vài lượt trước.
    single_turn: bool = True


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
    missing_sapo: int
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
    chuyen_muc_chinh: str | None   # chuyên mục gặp nhiều nhất trong các bài (đã gộp cách viết giữa các báo)
    first_seen: str                # bài đầu tiên của sự kiện (giờ VN)


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
    chuyen_muc_chinh: str | None


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


# ---------------------------------------------------------------- thống kê sự kiện + bản đồ 2D (trang "Dữ liệu & mô hình")
class SizeBin(BaseModel):
    nhan: str              # "1 bài", "2 bài", "3–4", …
    n: int                 # số sự kiện


class SourcesBin(BaseModel):
    so_bao: int            # 1–6 (6 = từ 6 báo trở lên)
    n: int                 # số sự kiện ≥ 2 bài


class DayStats(BaseModel):
    date: str
    so_bai: int                  # bài của run đăng trong ngày (giờ VN)
    so_su_kien: int              # sự kiện có ít nhất 1 bài trong ngày
    so_su_kien_nhieu_bai: int    # sự kiện có ≥ 2 bài TRONG ngày
    so_bao: int


class EventStats(BaseModel):
    n_su_kien: int
    n_su_kien_nhieu_bai: int
    kich_thuoc: list[SizeBin]
    so_bao: list[SourcesBin]
    chuyen_muc: list[CategoryN]  # chuyên mục chính của sự kiện ≥ 2 bài
    ngay: DayStats | None


class MapEvent(BaseModel):
    k: int                 # chỉ số màu; điểm có k này thuộc sự kiện
    event_id: str
    ten: str               # tên ĐANG HIỂN THỊ (đã áp luật ẩn tên)
    nguon_ten: str
    ten_bi_an: bool
    n: int                 # số bài của sự kiện trong ngày
    size: int
    n_sources: int


class EventMap(BaseModel):
    date: str
    run_id: str
    model_version: str
    tsne: dict[str, float | int | str]
    n_bai: int
    n_su_kien: int
    n_su_kien_nhieu_bai: int
    khac_run: bool             # bản đồ sinh từ run khác run đang phục vụ
    su_kien: list[MapEvent]
    diem: list[list[float]]    # [x, y, k] — x, y trong [0, 100]; k = -1: sự kiện khác
    ngay_co_san: list[str]


class MapDates(BaseModel):
    dates: list[str]
    mac_dinh: str | None


# ---------------------------------------------------------------- RAG đồng bộ tăng dần
class RAGSyncRequest(BaseModel):
    article_ids: list[str] | None = None


class RAGSyncAccepted(BaseModel):
    status: str              # "accepted" | "already_running" | "up_to_date"
    requested: int
    queued_articles: int
    already_ready: int
    missing_article_ids: list[str]
    message: str


class RAGSyncStatus(BaseModel):
    running: bool
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_result: dict | None = None
    last_error: str | None = None


# ---------------------------------------------------------------------- tài khoản (/api/auth, /api/me, /api/admin)
# Khớp lớp giả lập của web: apps/web/src/api/{auth,me,admin}.ts + mockdb.ts. Nghiệp vụ: src/eventrank/accounts/.
Role = Literal["user", "editor", "admin"]


class AccountUser(BaseModel):
    id: str
    email: str
    display_name: str
    role: Role
    email_verified: bool
    created_at: datetime


class RegisterBody(BaseModel):
    display_name: str = Field(max_length=200)
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    # `role` web gửi ở bản xem trước bị BỎ QUA: đăng ký luôn là `user` (admin tạo bằng CLI eventrank.accounts)


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    remember: bool = False


class TokenBody(BaseModel):
    token: str = Field(max_length=200)


class EmailBody(BaseModel):
    email: str = Field(max_length=254)


class ResetPasswordBody(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=256)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class EventSnapshot(BaseModel):
    event_id: str
    ten: str
    size: int
    n_sources: int
    chuyen_muc: str | None


class FollowItem(EventSnapshot):
    notify: bool
    at: datetime


class BookmarkItem(EventSnapshot):
    note: str
    at: datetime


class EventRef(BaseModel):
    event_id: str = Field(pattern=r"^E\d{8}-[0-9a-f]{8}$")


class BookmarkBody(EventRef):
    note: str = Field(default="", max_length=500)


class FollowUpdate(BaseModel):
    notify: bool


class Notification(BaseModel):
    id: str
    kind: str                  # nhãn hiển thị: "Hệ thống", "Sự kiện mới", …
    text: str
    event_id: str | None
    at: datetime
    read: bool


class Subscription(BaseModel):
    id: str
    kind: Literal["keyword", "category", "source", "entity"]
    value: str
    at: datetime


class SubscriptionBody(BaseModel):
    kind: Literal["keyword", "category", "source", "entity"]
    value: str = Field(max_length=200)


class Settings(BaseModel):
    push: bool
    digest: Literal["off", "daily", "weekly"]
    quiet_from: str            # "HH:MM", giờ Việt Nam
    quiet_to: str
    hidden_sources: list[str]


class SettingsPatch(BaseModel):
    push: bool | None = None
    digest: Literal["off", "daily", "weekly"] | None = None
    quiet_from: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_to: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    hidden_sources: list[Annotated[str, Field(max_length=40)]] | None = Field(default=None, max_length=50)


class SessionInfo(BaseModel):
    id: str
    device: str
    created_at: datetime
    last_seen: datetime
    current: bool


class FeedbackBody(BaseModel):
    kind: Literal["wrong_name", "stray_article", "duplicate", "other"]
    note: str = Field(default="", max_length=1000)
    event_name: str = Field(default="", max_length=300)   # web gửi kèm; máy chủ dùng tên đang hiển thị trong DB


class AdminUser(AccountUser):
    locked_until: datetime | None


class RoleBody(BaseModel):
    role: Role


class FeedbackItem(BaseModel):
    id: str
    event_id: str
    event_name: str
    kind: Literal["wrong_name", "stray_article", "duplicate", "other"]
    note: str
    who: str
    at: datetime
    status: Literal["open", "resolved", "rejected"]


class FeedbackUpdate(BaseModel):
    status: Literal["resolved", "rejected"]


class Mail(BaseModel):
    id: str
    at: datetime
    to: str
    kind: Literal["verify", "reset"]
    token: str
    used: bool
    expires_at: datetime | None


class ApiTokenInfo(BaseModel):
    id: str
    label: str
    source: str
    prefix: str
    created_at: datetime
    revoked: bool


class ApiTokenBody(BaseModel):
    label: str = Field(max_length=80)
    source: str = Field(default="", max_length=40)
    scope: Literal["ingest:write", "read"] = "ingest:write"


class ApiTokenCreated(BaseModel):
    token: str                 # khoá ĐẦY ĐỦ, chỉ trả một lần


# ---------------------------------------------------------------- hồ sơ cá nhân hoá chatbot (migration 010)
RAGPersona = Literal['pho_thong', 'doanh_nhan', 'ke_toan', 'nha_dau_tu', 'sinh_vien', 'giao_vien',
                     'can_bo_cong_chuc', 'nha_bao', 'lap_trinh_vien', 'khac']
RAGTone = Literal['than_thien', 'trang_trong', 'ngan_gon']
RAGLength = Literal['ngan', 'vua', 'chi_tiet']


class RAGProfile(BaseModel):
    persona: RAGPersona | None
    occupation_text: str | None
    address_user: str | None
    address_self: str | None
    tone: RAGTone | None
    answer_length: RAGLength | None
    interests: list[str]
    pending: dict[str, Any]          # thay đổi nghề/nhóm chatbot suy ra, chờ người dùng xác nhận


class RAGProfileUpdate(BaseModel):
    """Người dùng tự sửa hồ sơ; trường không gửi giữ nguyên, gửi null để xoá."""
    model_config = ConfigDict(extra='forbid')
    persona: RAGPersona | None = None
    occupation_text: str | None = Field(default=None, min_length=1, max_length=60)
    address_user: str | None = Field(default=None, min_length=1, max_length=30)
    address_self: str | None = Field(default=None, min_length=1, max_length=30)
    tone: RAGTone | None = None
    answer_length: RAGLength | None = None
    interests: list[str] | None = Field(default=None, max_length=10)


class RAGProfileConfirm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accept: bool
