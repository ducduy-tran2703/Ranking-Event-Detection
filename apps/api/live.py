"""`GET /api/live/overview`: số liệu trực tiếp của máy chủ (Postgres + dịch vụ crawler) cho trang "Dữ liệu máy chủ".

Logic ở `eventrank.serving.live_stats`; ở đây chỉ có HTTP và bộ đệm ngắn: trang web tự tải lại 30 s/lần, nhiều tab mở
cùng lúc vẫn chỉ chạy truy vấn 15 s/lần.

Trang công khai: khách và người không phải admin chỉ thấy tên lớp lỗi (`live_stats.public_view`), admin thấy nguyên văn.
Bộ đệm giữ cả hai bản, mỗi vai trò lấy đúng bản của mình.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from apps.api import schemas
from apps.api.accounts import Conn, optional_user
from eventrank.accounts.auth import CurrentUser
from eventrank.serving import live_stats

CACHE_SECONDS = 15.0

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/live", tags=["Số liệu trực tiếp"])
_lock = threading.Lock()


def valid_crawler(crawler: dict[str, Any] | None) -> dict[str, Any] | None:
    """Crawler trả trường sai kiểu (ngày không đọc được, id là số, số đếm null…) → coi như không trả lời (None)
    thay vì để response_model ném lỗi 500 cho cả trang."""
    if crawler is None:
        return None
    try:
        schemas.LiveCrawler.model_validate(crawler)
    except ValidationError:
        log.warning("dịch vụ crawler trả dữ liệu sai kiểu; bỏ phần crawler của /api/live/overview")
        return None
    return crawler


@router.get("/overview", response_model=schemas.LiveOverview)
def overview(request: Request, conn: Conn,
             user: Annotated[CurrentUser | None, Depends(optional_user)]) -> Any:
    st = request.app.state
    view = "admin" if user is not None and user.role == "admin" else "public"
    cached = getattr(st, "live_cache", None)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1][view]
    with _lock:
        cached = getattr(st, "live_cache", None)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1][view]
        crawler = valid_crawler(live_stats.crawler_status(getattr(st, "crawler_url", None)))
        try:
            data = live_stats.live_overview(conn, crawler)
        except psycopg.errors.UndefinedTable as exc:     # DB chưa áp migration 001/002/007
            raise HTTPException(503, "Postgres chưa áp đủ migration (make db-migrate).") from exc
        st.live_cache = (time.monotonic(), {"admin": data, "public": live_stats.public_view(data)})
        return st.live_cache[1][view]
