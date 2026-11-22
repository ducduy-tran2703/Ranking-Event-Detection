"""Cài đặt chạy-khi-đang-chạy của worker sự kiện (`make worker --loop`): khối `event_worker` trong `system_settings`.

Tách khỏi `worker.py` để API đọc/ghi được mà không phải import cả chuỗi embedding/gom cụm/đặt tên (nặng RAM).
- `enabled = false`: worker `--loop` bỏ qua vòng (vẫn sống, đọc lại cài đặt định kỳ); `--once` vẫn chạy.
- `interval_seconds`: thay `worker.interval_seconds` của configs/pipeline.yaml; đổi trên web có hiệu lực trong ≤ 30 s.
- Chưa có dòng / DB chưa áp migration 011 → mặc định lấy từ pipeline.yaml (như trước khi có trang cài đặt).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from eventrank.common import settings_store

ROOT = Path(__file__).resolve().parents[3]
PIPELINE_CONFIG = ROOT / "configs/pipeline.yaml"
SETTINGS_KEY = "event_worker"
INTERVALS = (60, 120, 300, 600, 900, 1800, 3600)
YAML_DEFAULT_SECONDS = 300


class EventWorkerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_seconds: Literal[60, 120, 300, 600, 900, 1800, 3600] = 300


def nearest_interval(seconds: float) -> int:
    """Giá trị trong YAML không thuộc danh sách chọn trên web → lấy mức gần nhất (hoà thì mức nhỏ hơn)."""
    return min(INTERVALS, key=lambda v: (abs(v - float(seconds)), v))


def yaml_interval(path: str | Path = PIPELINE_CONFIG) -> float:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return float((raw.get("worker") or {}).get("interval_seconds", YAML_DEFAULT_SECONDS))
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        return float(YAML_DEFAULT_SECONDS)


def default_settings(interval_seconds: float | None = None) -> EventWorkerSettings:
    seconds = yaml_interval() if interval_seconds is None else interval_seconds
    return EventWorkerSettings(interval_seconds=nearest_interval(seconds))


def load(conn, default: EventWorkerSettings | None = None) -> settings_store.Stored[EventWorkerSettings]:
    return settings_store.load(conn, SETTINGS_KEY, EventWorkerSettings, default or default_settings())


def save(conn, value: EventWorkerSettings, user_id: int | None = None):
    return settings_store.save(conn, SETTINGS_KEY, value, user_id)
