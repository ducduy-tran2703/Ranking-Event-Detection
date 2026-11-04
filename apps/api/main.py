"""FastAPI: trang kiểm soát dữ liệu Silver + web demo sự kiện. Chỉ đọc — không có endpoint ghi hay xoá dữ liệu kho.

Sự kiện (/api/trending, /api/events, /api/runs/current) đọc kết quả MỘT lần chạy pipeline: `EVENTS_BACKEND=files` (mặc
định — `EventStore`, `EVENTS_RUN_DIR` hoặc run mới nhất trong data/runs/) hoặc `db` (`DbEventStore`, Postgres DATABASE_URL,
nạp bằng `make db-import-run`). Chưa có dữ liệu → các endpoint đó trả 503, phần Silver vẫn chạy.
Tên sự kiện giao cửa sổ `EVENTS_HIDE_NAMES_WINDOW` (mặc định 14–15/09/2026) bị ẩn — xem eventrank/serving/store.py.

Chạy:  uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from apps.api import schemas
from eventrank.common.config import load_config
from eventrank.lake.reader import Filters, SilverStore
from eventrank.serving.db_store import DbEventStore, event_store_from_env
from eventrank.serving.store import (
    DEFAULT_MAP_DATE,
    EVENT_ID_PATTERN,
    NO_RUN_MESSAGE,
    EventStore,
    HiddenDateError,
    HideWindowError,
    MapNotFound,
    RunNotFound,
    rel_label,
)

log = logging.getLogger(__name__)
ulog = logging.getLogger("uvicorn.error")   # logger uvicorn đã cấu hình sẵn → dòng log hiện trên terminal

STATIC_DIR = Path(__file__).parent / "static"          # trang kiểm soát nội bộ (HTML/JS thuần)
WEB_DIST = Path(__file__).parent.parent / "web" / "dist"  # web React đã đóng gói (make build)
DATE = r"^\d{4}-\d{2}-\d{2}$"


def _unauthorized() -> Response:
    return Response("Cần đăng nhập", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Su kien tin tuc"'})


def add_basic_auth(app: FastAPI) -> None:
    """Bảo vệ toàn trang bằng mật khẩu khi đặt DASHBOARD_USER và DASHBOARD_PASSWORD.

    Dùng khi mở trang ra Internet (ví dụ qua Cloudflare Tunnel). Không đặt hai biến này
    thì trang mở tự do — chỉ phù hợp khi chạy trên máy cá nhân (127.0.0.1).
    """
    user = os.environ.get("DASHBOARD_USER", "")
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not (user and password):
        return

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            import base64
            try:
                got_user, _, got_pass = base64.b64decode(header[6:]).decode().partition(":")
            except Exception:  # noqa: BLE001 - header hỏng thì coi như chưa đăng nhập
                return _unauthorized()
            # compare_digest: so sánh trong thời gian không đổi, tránh dò mật khẩu qua thời gian phản hồi
            if secrets.compare_digest(got_user, user) and secrets.compare_digest(got_pass, password):
                return await call_next(request)
        return _unauthorized()


def get_store(request: Request) -> SilverStore:
    return request.app.state.store


def get_filters(
    source: str | None = None,
    category: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    date_from: Annotated[str | None, Query(pattern=DATE)] = None,
    date_to: Annotated[str | None, Query(pattern=DATE)] = None,
    issue: str | None = None,
) -> Filters:
    return Filters(source=source or None, category=category or None, q=q or None,
                   date_from=date_from or None, date_to=date_to or None, issue=issue or None)


def get_events(request: Request) -> EventStore:
    ev = request.app.state.events
    if ev is None:
        raise HTTPException(503, request.app.state.events_error or NO_RUN_MESSAGE)
    return ev


Store = Annotated[SilverStore, Depends(get_store)]
Filt = Annotated[Filters, Depends(get_filters)]
Events = Annotated[EventStore, Depends(get_events)]


def create_app(store: SilverStore | None = None, events: EventStore | None = None,
               load_events: bool | None = None) -> FastAPI:
    """`load_events`: tự nạp kết quả pipeline lúc khởi động (mặc định: chỉ khi không truyền `store`, tức chạy thật)."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.store is None:                      # test truyền store sẵn thì bỏ qua
            s = SilverStore(load_config())
            s.reload()
            app.state.store = s
        if app.state.events is None and (store is None if load_events is None else load_events):
            try:
                ev = event_store_from_env()
                app.state.events = ev
                ulog.info("sự kiện: run %s (%s), nạp %.2fs; ẩn tên %d sự kiện (%d trong cửa sổ, %d gần trùng)",
                          ev.run_id, "Postgres" if isinstance(ev, DbEventStore) else rel_label(ev.run_dir),
                          ev.load_seconds, ev.n_hidden_window + ev.n_hidden_near,
                          ev.n_hidden_window, ev.n_hidden_near)
            except Exception as exc:  # noqa: BLE001 - thiếu/hỏng run chỉ tắt phần sự kiện (503), không tắt cả API
                log.warning("không nạp được kết quả pipeline sự kiện: %r", exc)
                ulog.warning("không nạp được kết quả pipeline sự kiện: %r", exc)
                # Trả cho trình duyệt thông báo không chứa đường dẫn tuyệt đối; chi tiết ở log server.
                app.state.events_error = (str(exc) if isinstance(exc, (RunNotFound, HideWindowError))
                                          else f"Không nạp được kết quả pipeline sự kiện (xem log server). "
                                               f"{NO_RUN_MESSAGE}")
        yield

    app = FastAPI(title="Ranking-Event-Detection — Kiểm soát dữ liệu", lifespan=lifespan)
    app.state.store = store
    app.state.events = events
    app.state.events_error = None

    @app.exception_handler(ValueError)
    async def bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/health", response_model=schemas.Health)
    def health(s: Store) -> dict[str, Any]:
        return {"status": "ok", "rows": s.count(), "loaded_at": s.loaded_at}

    @app.get("/api/meta", response_model=schemas.Meta)
    def meta(s: Store) -> dict[str, Any]:
        return s.meta()

    @app.get("/api/files", response_model=list[schemas.FileInfo])
    def files(s: Store) -> list[dict[str, Any]]:
        return s.list_files(max_age_s=60)

    @app.get("/api/freshness", response_model=schemas.Freshness)
    def freshness(s: Store) -> dict[str, Any]:
        """Dữ liệu đang dùng có cũ hơn kho không. Kết quả liệt kê file được dùng lại trong 60 giây."""
        return s.freshness(max_age_s=60)

    @app.get("/api/stats/overview", response_model=schemas.Overview)
    def overview(s: Store) -> dict[str, Any]:
        return s.overview()

    @app.get("/api/stats/timeline", response_model=list[schemas.TimelinePoint])
    def timeline(s: Store, f: Filt, granularity: str = "day") -> list[dict[str, Any]]:
        return s.timeline(f, granularity)

    @app.get("/api/stats/hour-of-day", response_model=list[schemas.HourPoint])
    def hour_of_day(s: Store, f: Filt) -> list[dict[str, Any]]:
        return s.hour_of_day(f)

    @app.get("/api/stats/categories", response_model=list[schemas.CategoryCount])
    def categories(s: Store, f: Filt) -> list[dict[str, Any]]:
        return s.categories(f)

    @app.get("/api/stats/quality", response_model=schemas.Quality)
    def quality(s: Store) -> dict[str, Any]:
        return s.quality()

    @app.get("/api/articles", response_model=schemas.ArticlePage)
    def articles(
        s: Store,
        f: Filt,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        sort: str = "newest",
    ) -> dict[str, Any]:
        return s.list_articles(f, page, page_size, sort)

    @app.get("/api/articles/{article_id}", response_model=schemas.ArticleDetail)
    def article(article_id: str, s: Store) -> dict[str, Any]:
        row = s.get_article(article_id)
        if row is None:
            raise HTTPException(404, "Không tìm thấy bài")
        return row

    # ------------------------------------------------------------ sự kiện (kết quả pipeline)
    @app.get("/api/runs/current", response_model=schemas.RunInfo)
    def run_current(ev: Events) -> dict[str, Any]:
        """Lần chạy pipeline đang phục vụ: phiên bản, số lượng, các hạn chế cần ghi rõ trên giao diện."""
        return ev.run_info()

    @app.get("/api/trending/times", response_model=schemas.TrendTimes)
    def trending_times(ev: Events) -> dict[str, Any]:
        """Khoảng mốc giờ có bảng xu hướng + số sự kiện trên bảng ở từng mốc (cho thanh trượt phát lại)."""
        return ev.trend_times()

    @app.get("/api/trending", response_model=schemas.Trending)
    def trending_at(ev: Events, t: Annotated[str | None, Query(max_length=40)] = None) -> dict[str, Any]:
        """Top-20 xu hướng tại mốc t (ISO; không múi giờ = giờ VN; làm tròn xuống theo giờ). Bỏ trống → mốc mặc định."""
        if not t:
            return ev.trending()
        try:
            k = ev.parse_t(t)
        except ValueError as exc:
            raise HTTPException(422, f"t không hợp lệ: {exc}") from exc
        return ev.trending(k)

    @app.get("/api/events", response_model=schemas.EventPage)
    def events_list(
        ev: Events,
        q: Annotated[str | None, Query(max_length=200)] = None,
        source: Annotated[str | None, Query(max_length=40)] = None,
        category: Annotated[str | None, Query(max_length=80)] = None,
        date_from: Annotated[str | None, Query(pattern=DATE)] = None,
        date_to: Annotated[str | None, Query(pattern=DATE)] = None,
        first_from: Annotated[str | None, Query(max_length=40)] = None,
        first_to: Annotated[str | None, Query(max_length=40)] = None,
        min_size: Annotated[int, Query(ge=1)] = 2,
        sort: Literal["hot", "newest", "size", "first_seen"] = "hot",
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """Danh sách sự kiện. q khớp tên ĐANG HIỂN THỊ hoặc tiêu đề bài đại diện (không phân biệt hoa/thường, dấu).
        category = chuyên mục chính; first_from/first_to (ISO, không múi giờ = giờ VN) lọc theo lúc xuất hiện;
        sort=first_seen: xuất hiện muộn nhất trước."""
        try:
            return ev.list_events(q=q or None, source=source or None, date_from=date_from or None,
                                  date_to=date_to or None, min_size=min_size, sort=sort, page=page,
                                  page_size=page_size, category=category or None, first_from=first_from or None,
                                  first_to=first_to or None)
        except ValueError as exc:            # ngày đúng dạng nhưng không có trên lịch (2026-02-30)
            raise HTTPException(422, f"Tham số không hợp lệ: {exc}") from exc

    # Ba đường dẫn dưới phải khai báo TRƯỚC /api/events/{event_id}.
    @app.get("/api/events/stats", response_model=schemas.EventStats)
    def events_stats(ev: Events, date: Annotated[str | None, Query(pattern=DATE)] = None) -> dict[str, Any]:
        """Số đếm (không có tên): kích thước sự kiện, số báo, chuyên mục; `date` → thêm số liệu của ngày đó."""
        try:
            return ev.stats(date or None)
        except ValueError as exc:
            raise HTTPException(422, f"Tham số không hợp lệ: {exc}") from exc

    @app.get("/api/events/map/dates", response_model=schemas.MapDates)
    def events_map_dates(ev: Events) -> dict[str, Any]:
        """Các ngày đã có bản đồ 2D (không gồm ngày thuộc cửa sổ ẩn tên)."""
        dates = ev.map_dates()
        return {"dates": dates, "mac_dinh": DEFAULT_MAP_DATE if DEFAULT_MAP_DATE in dates else
                (dates[0] if dates else None)}

    @app.get("/api/events/map", response_model=schemas.EventMap)
    def events_map(ev: Events, date: Annotated[str | None, Query(pattern=DATE)] = None) -> dict[str, Any]:
        """Bản đồ t-SNE các bài của một ngày + tên đang hiển thị của các sự kiện lớn nhất. Ngày trong cửa sổ ẩn tên → 403."""
        if not date:
            dates = ev.map_dates()
            date = DEFAULT_MAP_DATE if DEFAULT_MAP_DATE in dates or not dates else dates[0]
        try:
            return ev.event_map(date)
        except HiddenDateError as exc:
            raise HTTPException(403, str(exc)) from exc
        except MapNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, f"Tham số không hợp lệ: {exc}") from exc

    @app.get("/api/events/{event_id}", response_model=schemas.EventDetail)
    def event_detail(ev: Events, s: Store,
                     event_id: Annotated[str, PathParam(pattern=EVENT_ID_PATTERN)]) -> dict[str, Any]:
        """Một sự kiện: các bài (kèm URL từ Silver nếu có), số bài + điểm xu hướng theo giờ trên toàn đời sống."""
        row = ev.get_event(event_id, urls=getattr(s, "urls", None))
        if row is None:
            raise HTTPException(404, "Không tìm thấy sự kiện")
        return row

    @app.post("/api/admin/reload", response_model=schemas.ReloadResult)
    def reload(s: Store) -> dict[str, Any]:
        return s.reload()

    add_basic_auth(app)

    # Trang kiểm soát nội bộ luôn có ở /legacy (chạy được kể cả khi chưa đóng gói web React)
    app.mount("/legacy", StaticFiles(directory=STATIC_DIR, html=True), name="legacy")

    if (WEB_DIST / "index.html").exists():
        # Đã chạy `make build`: phục vụ web React ở gốc, một địa chỉ duy nhất cho cả web và API.
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> Response:
            """Mọi đường dẫn không phải API đều trả index.html để React tự định tuyến."""
            if full_path.startswith(("api/", "legacy/", "docs", "openapi.json")):
                raise HTTPException(404, "Không tìm thấy")
            candidate = (WEB_DIST / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(WEB_DIST.resolve()):
                return FileResponse(candidate)          # favicon, robots.txt…
            return FileResponse(WEB_DIST / "index.html")
    else:
        # Chưa đóng gói web React: gốc trỏ về trang kiểm soát nội bộ.
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


app = create_app()
