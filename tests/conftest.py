import pytest

from eventrank.common.config import LakeConfig
from eventrank.lake.reader import SilverStore


@pytest.fixture(scope="session")
def local_cfg() -> LakeConfig:
    """Đọc dữ liệu mẫu cục bộ — test không bao giờ chạm vào R2."""
    return LakeConfig(backend="local", bucket="", silver_glob="silver/*/*.jsonl",
                      local_root="tests/fixtures")


@pytest.fixture(scope="session")
def store(local_cfg) -> SilverStore:
    s = SilverStore(local_cfg)
    s.reload()
    return s
