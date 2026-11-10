"""Nạp lại sự kiện từ Postgres khi worker có dữ liệu mới, không phải khởi động lại API.

Một luồng nền hỏi `worker_runs` mỗi `EVENTS_RELOAD_SECONDS` giây (mặc định 60; 0 = tắt). Dữ liệu mới được dựng xong trong
một `DbEventStore` riêng rồi mới gán vào `app.state.events`, nên yêu cầu đang chạy không thấy trạng thái dở dang. Lỗi khi nạp
lại chỉ ghi log và giữ nguyên dữ liệu cũ.
"""
from __future__ import annotations

import logging
import os
import threading

from eventrank.common import db
from eventrank.serving.db_store import DbEventStore

log = logging.getLogger(__name__)
DEFAULT_SECONDS = 60.0


class EventReloader:
    def __init__(self, app, interval: float):
        self.app = app
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="event-reloader", daemon=True)

    @classmethod
    def start_if_db(cls, app) -> EventReloader | None:
        """Chỉ chạy khi API đang đọc Postgres và không tắt bằng EVENTS_RELOAD_SECONDS=0."""
        interval = float(os.environ.get("EVENTS_RELOAD_SECONDS") or DEFAULT_SECONDS)
        if interval <= 0 or not isinstance(app.state.events, DbEventStore):
            return None
        reloader = cls(app, interval)
        reloader._thread.start()
        return reloader

    def check_once(self) -> bool:
        """Trả True nếu vừa thay dữ liệu."""
        current = self.app.state.events
        with db.connect() as conn:
            if DbEventStore.current_version(conn) == current.data_version:
                return False
            fresh = DbEventStore(conn, current.hide_window)
        self.app.state.events = fresh
        log.info("đã nạp lại sự kiện từ Postgres (phiên bản %s, %.2f s)", fresh.data_version, fresh.load_seconds)
        return True

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check_once()
            except Exception:
                log.exception("không nạp lại được sự kiện từ Postgres; giữ dữ liệu cũ")

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
