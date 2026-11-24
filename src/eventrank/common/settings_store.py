"""Kho cài đặt hệ thống trong Postgres (bảng `system_settings`, migration 011), đọc/ghi theo khối.

Mỗi khối là một key (`rag_sync`, `event_worker`) và một model Pydantic do MODULE SỞ HỮU khai báo (tầng `common` không
biết các khối cụ thể). Quy tắc đọc:

- Chưa có dòng, hoặc DB chưa áp 011 (bảng chưa có) → trả mặc định, không lỗi: tiến trình cũ vẫn chạy như trước.
- Dòng có trường thừa/thiếu (code mới hơn hoặc cũ hơn DB) → giữ các trường còn hợp lệ, phần còn lại lấy mặc định.
- Trường có giá trị không qua kiểm tra (ai đó sửa tay sai) → riêng trường đó lấy mặc định, các trường khác giữ, ghi
  log cảnh báo; không làm chết vòng lặp gọi tới.

Ghi luôn kiểm bằng model trước (sai → `ValidationError`, không ghi gì).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


@dataclass
class Stored[T]:
    value: T
    updated_at: datetime | None = None
    updated_by: int | None = None
    from_db: bool = False            # False: chưa có dòng hoặc bảng chưa có → đang dùng mặc định


def available(conn: psycopg.Connection) -> bool:
    """Bảng `system_settings` đã có chưa (migration 011)."""
    return conn.execute("SELECT to_regclass('system_settings') IS NOT NULL").fetchone()[0]


def load[M: BaseModel](conn: psycopg.Connection, key: str, model: type[M], default: M | None = None) -> Stored[M]:
    base = default if default is not None else model()
    try:
        row = conn.execute("SELECT value, updated_at, updated_by FROM system_settings WHERE key = %s",
                           (key,)).fetchone()
    except psycopg.errors.UndefinedTable:
        return Stored(base)
    if row is None:
        return Stored(base)
    raw, updated_at, updated_by = row
    fields = set(model.model_fields)
    known = {k: v for k, v in (raw or {}).items() if k in fields} if isinstance(raw, dict) else {}
    merged, bad = base.model_dump(), []
    for k, v in known.items():           # kiểm từng trường: một trường sai không kéo cả khối (vd. enabled=false) về mặc định
        try:
            model.model_validate({**merged, k: v})
        except ValidationError:
            bad.append(k)
        else:
            merged[k] = v
    try:
        value = model.model_validate(merged)
    except ValidationError:              # luật liên trường của model vẫn sai → cả khối mặc định
        bad, value = list(known), base
    if bad:
        log.warning("cài đặt %s trong system_settings có trường không hợp lệ (%s); trường đó dùng mặc định",
                    key, ", ".join(bad))
    return Stored(value, updated_at, updated_by, True)


def get[M: BaseModel](conn: psycopg.Connection, key: str, model: type[M], default: M | None = None) -> M:
    return load(conn, key, model, default).value


def save[M: BaseModel](conn: psycopg.Connection, key: str, value: M, user_id: int | None = None) -> Stored[M]:
    """Ghi đè cả khối (đã kiểm). Bảng chưa có → `psycopg.errors.UndefinedTable` cho tầng gọi đổi thành 503."""
    value = type(value).model_validate(value.model_dump())
    row = conn.execute(
        "INSERT INTO system_settings (key, value, updated_by) VALUES (%s, %s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now() "
        "RETURNING updated_at, updated_by", (key, Jsonb(value.model_dump(mode="json")), user_id)).fetchone()
    return Stored(value, row[0], row[1], True)
