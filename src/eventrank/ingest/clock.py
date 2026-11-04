"""Đồng hồ của hệ thống (bảng `app_clock`, đúng một dòng).

- `real`: "bây giờ" = giờ thật (`now()`), dùng khi crawler cào bài thật.
- `replay`: "bây giờ" = `sim_now` do `ingest replay` đẩy tới — phát lại Silver cũ như thể bài
  đang đến, thay crawler khi chưa có. `sim_now` chỉ đổi khi replay chạy một nhịp: dừng replay thì
  đồng hồ đứng yên (không ngoại suy theo `speed`), vì bài sau `sim_now` chưa được đưa vào DB.

Worker/API giai đoạn 2 đọc "bây giờ" từ đây (SQL: `SELECT app_now()`; Python: `app_now(conn)`),
không gọi `datetime.now()` trực tiếp — để cùng một code chạy được cả demo phát lại lẫn chạy thật.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass(frozen=True)
class Clock:
    mode: str
    sim_now: datetime | None
    speed: float
    updated_at: datetime


def read_clock(conn: psycopg.Connection) -> Clock:
    row = conn.execute("SELECT mode, sim_now, speed, updated_at FROM app_clock").fetchone()
    if row is None:
        raise RuntimeError("Bảng app_clock rỗng — chạy `make db-migrate`")
    return Clock(*row)


def app_now(conn: psycopg.Connection) -> datetime:
    return conn.execute("SELECT app_now()").fetchone()[0]


def set_replay(conn: psycopg.Connection, sim_now: datetime, speed: float) -> None:
    conn.execute("UPDATE app_clock SET mode = 'replay', sim_now = %s, speed = %s, "
                 "updated_at = now()", (sim_now, speed))


def set_real(conn: psycopg.Connection) -> None:
    conn.execute("UPDATE app_clock SET mode = 'real', sim_now = NULL, speed = 1, "
                 "updated_at = now()")
