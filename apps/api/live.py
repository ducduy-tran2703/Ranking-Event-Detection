"""`GET /api/live/overview`: số liệu trực tiếp của máy chủ (Postgres + dịch vụ crawler) cho trang "Dữ liệu máy chủ".

Logic ở `eventrank.serving.live_stats`; ở đây chỉ có HTTP và bộ đệm ngắn: trang web tự tải lại 30 s/lần, nhiều tab mở
cùng lúc vẫn chỉ chạy truy vấn 15 s/lần.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Request

from apps.api import schemas
from apps.api.accounts import Conn
from eventrank.serving import live_stats

CACHE_SECONDS = 15.0

router = APIRouter(prefix="/api/live", tags=["Số liệu trực tiếp"])
_lock = threading.Lock()


@router.get("/overview", response_model=schemas.LiveOverview)
def overview(request: Request, conn: Conn) -> Any:
    st = request.app.state
    cached = getattr(st, "live_cache", None)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    with _lock:
        cached = getattr(st, "live_cache", None)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        crawler = live_stats.crawler_status(getattr(st, "crawler_url", None))
        try:
            data = live_stats.live_overview(conn, crawler)
        except psycopg.errors.UndefinedTable as exc:     # DB chưa áp migration 001/002/007
            raise HTTPException(503, "Postgres chưa áp đủ migration (make db-migrate).") from exc
        st.live_cache = (time.monotonic(), data)
        return data
