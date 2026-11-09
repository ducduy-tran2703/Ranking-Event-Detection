from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from automation.config import SOURCES

Source = Literal["baochinhphu", "nhandan", "dantri", "qdnd", "tuoitre", "thanhnien", "vietnamnet", "vnexpress"]


class CrawlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[Source] = Field(default_factory=lambda: list(SOURCES), min_length=1)
    retry_failed: bool = False


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    interval_minutes: Literal[5, 10, 15, 20, 30, 60] | None = None
    sources: list[Source] | None = Field(default=None, min_length=1)
