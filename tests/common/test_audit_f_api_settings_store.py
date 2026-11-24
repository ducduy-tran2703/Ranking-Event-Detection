"""Pha sửa (agent F-api), AUDIT-P1-crawl-worker-9: một trường sai trong `system_settings` chỉ làm TRƯỜNG ĐÓ về mặc
định, các trường hợp lệ khác (vd. `enabled=false` của worker đang tạm dừng) được giữ. Kết nối giả, không cần DB."""
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, Field

from eventrank.common import settings_store as S


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_seconds: int = Field(300, ge=60, le=3600)
    note: str = "mặc định"


class _Conn:
    def __init__(self, raw):
        self.row = (raw, None, None)

    def execute(self, sql, params=None):
        return SimpleNamespace(fetchone=lambda: self.row)


@pytest.mark.parametrize("bad", [45, "không phải số", None, [1]])
def test_mot_truong_sai_chi_truong_do_ve_mac_dinh(bad):
    got = S.load(_Conn({"enabled": False, "interval_seconds": bad, "note": "giữ"}), "block", Block)
    assert got.from_db and got.value == Block(enabled=False, interval_seconds=300, note="giữ")


def test_truong_sai_lay_mac_dinh_truyen_vao():
    got = S.get(_Conn({"enabled": False, "interval_seconds": 5}), "block", Block, Block(interval_seconds=600))
    assert got == Block(enabled=False, interval_seconds=600)


def test_nhieu_truong_sai_van_giu_truong_dung():
    got = S.get(_Conn({"enabled": "khong-ro", "interval_seconds": 9999, "note": "ok"}), "block", Block)
    assert got == Block(note="ok")
