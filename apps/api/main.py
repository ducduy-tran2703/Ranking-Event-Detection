"""FastAPI: trang kiểm soát dữ liệu Silver. Chỉ đọc — không có endpoint ghi hay xoá dữ liệu kho.

Chạy:  uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from apps.api import schemas
from eventrank.common.config import load_config
from eventrank.lake.reader import Filters, SilverStore

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


Store = Annotated[SilverStore, Depends(get_store)]
Filt = Annotated[Filters, Depends(get_filters)]


def create_app(store: SilverStore | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.store is None:                      # test truyền store sẵn thì bỏ qua
            s = SilverStore(load_config())
            s.reload()
            app.state.store = s
        yield

    app = FastAPI(title="Ranking-Event-Detection — Kiểm soát dữ liệu", lifespan=lifespan)
    app.state.store = store

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
