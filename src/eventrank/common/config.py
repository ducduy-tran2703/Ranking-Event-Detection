"""Cấu hình đọc từ biến môi trường / file .env. Không bao giờ in giá trị khoá."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class LakeConfig:
    backend: str                 # "r2" hoặc "local"
    bucket: str
    silver_glob: str             # đường dẫn tương đối trong bucket / thư mục
    local_root: str
    account_id: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None

    @property
    def silver_uri(self) -> str:
        if self.backend == "r2":
            return f"r2://{self.bucket}/{self.silver_glob}"
        return os.path.join(self.local_root, self.silver_glob)

    def describe(self) -> str:
        """Mô tả an toàn để hiển thị — không chứa khoá."""
        if self.backend == "r2":
            return f"r2://{self.bucket}/{self.silver_glob}"
        return f"local:{self.silver_uri}"


def load_config() -> LakeConfig:
    load_dotenv()
    backend = os.environ.get("LAKE_BACKEND", "r2").lower()
    if backend not in ("r2", "local"):
        raise ValueError(f"LAKE_BACKEND không hợp lệ: {backend}")
    cfg = LakeConfig(
        backend=backend,
        bucket=os.environ.get("R2_BUCKET", ""),
        silver_glob=os.environ.get("LAKE_SILVER_GLOB", "silver/*/*.jsonl"),
        local_root=os.environ.get("LAKE_LOCAL_ROOT", "data/lake"),
        account_id=os.environ.get("R2_ACCOUNT_ID"),
        access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
        secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
    )
    if backend == "r2":
        missing = [n for n, v in [("R2_BUCKET", cfg.bucket), ("R2_ACCOUNT_ID", cfg.account_id),
                                  ("R2_ACCESS_KEY_ID", cfg.access_key_id),
                                  ("R2_SECRET_ACCESS_KEY", cfg.secret_access_key)] if not v]
        if missing:
            raise ValueError(f"Thiếu biến môi trường: {', '.join(missing)}")
    return cfg
