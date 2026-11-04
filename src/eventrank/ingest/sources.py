"""Đọc danh sách nguồn (`configs/sources.yaml`) và nạp lớp crawler đã đăng ký ("module:Lớp")."""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
SOURCES_YAML = ROOT / "configs/sources.yaml"
_SOURCE = re.compile(r"^[a-z0-9_]+$")
_SPEC = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


class SourceConfigError(ValueError):
    pass


def load_sources(path: Path | str = SOURCES_YAML) -> list[dict[str, Any]]:
    """Danh sách nguồn đã kiểm tra: source đúng mẫu, không trùng, crawler đúng dạng "module:Lớp"."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rows = data.get("sources") or []
    seen: set[str] = set()
    out = []
    for r in rows:
        src = str(r.get("source", ""))
        if not _SOURCE.match(src):
            raise SourceConfigError(f"source phải viết thường, không dấu: {src!r}")
        if src in seen:
            raise SourceConfigError(f"source trùng: {src}")
        seen.add(src)
        crawler = (r.get("crawler") or "").strip()
        if crawler and not _SPEC.match(crawler):
            raise SourceConfigError(f"{src}: crawler phải dạng 'module:Lớp', nhận {crawler!r}")
        out.append({**r, "source": src, "crawler": crawler or None,
                    "display_name": r.get("display_name") or src,
                    "enabled": bool(r.get("enabled", False))})
    return out


def load_crawler(spec: str):
    """Tạo crawler từ "module:Lớp" (khởi tạo không tham số)."""
    module, _, cls = spec.partition(":")
    obj = getattr(importlib.import_module(module), cls)
    return obj()
