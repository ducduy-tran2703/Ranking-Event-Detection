import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("baochinhphu", "nhandan", "dantri", "qdnd", "tuoitre", "thanhnien", "vietnamnet", "vnexpress")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("CRAWLER_DATA_DIR", str(ROOT / "data"))).resolve())
    workers_per_source: int = 2
    timeout: float = 15
    overlap_hours: int = 24
    initial_lookback_hours: int = 24
    max_listing_pages: int = 100
    bootstrap_listing_pages: int = 3
    max_article_attempts: int = 5
    scheduler_enabled: bool = True
    # Minimum spacing between request STARTS, including discovery and retries.
    delays: dict = field(default_factory=lambda: {
        "baochinhphu": 2.0, "nhandan": 2.0, "dantri": 4.0, "qdnd": 2.0,
        "tuoitre": 2.0, "thanhnien": 2.0, "vietnamnet": 2.0, "vnexpress": 2.0})

    def __post_init__(self):
        if self.workers_per_source < 1 or self.max_listing_pages < 2:
            raise ValueError("workers_per_source >= 1 and max_listing_pages >= 2 required")
        if not 1 <= self.bootstrap_listing_pages <= self.max_listing_pages:
            raise ValueError("bootstrap_listing_pages must be within the page limit")
        if self.timeout <= 0 or self.max_article_attempts < 1:
            raise ValueError("timeout and max_article_attempts must be positive")
        if self.overlap_hours < 0 or self.initial_lookback_hours <= 0:
            raise ValueError("Invalid lookback/overlap")
        if any(self.delays.get(source, -1) < 0 for source in SOURCES):
            raise ValueError("Every source needs a nonnegative delay")
