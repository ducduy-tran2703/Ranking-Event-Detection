"""Worker sự kiện đọc cài đặt `event_worker` động (trang Cài đặt hệ thống): tạm dừng, đổi chu kỳ, thiếu migration 011."""
from types import SimpleNamespace

import psycopg
import pytest

from eventrank.common import settings_store
from eventrank.serving import worker as W
from eventrank.serving import worker_settings as WS


def _cfg(seconds=300):
    return SimpleNamespace(worker={"interval_seconds": seconds})


class _Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _settings_seq(monkeypatch, values):
    """Mỗi lần đọc cài đặt trả phần tử kế tiếp (phần tử cuối lặp lại mãi)."""
    it = iter(values)
    last = {"v": None}

    def load(conn, default=None):
        try:
            last["v"] = next(it)
        except StopIteration:
            pass
        v = last["v"]
        return v if isinstance(v, settings_store.Stored) else settings_store.Stored(v, from_db=True)
    monkeypatch.setattr(W.WS, "load", load)


def test_mac_dinh_lay_tu_pipeline_yaml_lam_tron_ve_muc_gan_nhat():
    assert WS.default_settings(300) == WS.EventWorkerSettings(enabled=True, interval_seconds=300)
    assert WS.default_settings(45).interval_seconds == 60
    assert WS.default_settings(5000).interval_seconds == 3600
    assert WS.yaml_interval() == 300            # configs/pipeline.yaml hiện đặt 300 s


@pytest.mark.parametrize("bad", [{"interval_seconds": 61}, {"enabled": "có lẽ"}, {"khac": 1}])
def test_cai_dat_sai_bi_tu_choi(bad):
    with pytest.raises(ValueError):
        WS.EventWorkerSettings(**bad)


def test_chua_co_dong_hoac_chua_ap_011_thi_dung_yaml_nguyen_gia_tri():
    class _Conn:
        def execute(self, sql, params=None):
            raise psycopg.errors.UndefinedTable("relation system_settings does not exist")
    got = W.current_settings(_Conn(), _cfg(45))
    assert got == W.LoopSettings(True, 45.0)


def test_tat_thi_bo_vong_doi_chu_ky_co_hieu_luc_khi_dang_cho(monkeypatch):
    clock, ran, logs = _Clock(), [], []
    _settings_seq(monkeypatch, [WS.EventWorkerSettings(enabled=False, interval_seconds=60)])
    W.loop_forever(object(), _cfg(), run=lambda c, k: ran.append(1) or {}, sleep=clock.sleep, clock=clock,
                   logf=logs.append, max_rounds=3)
    assert ran == [] and sum("TẠM DỪNG" in m for m in logs) == 1     # báo một lần, không spam log
    assert clock.sleeps == [30, 30] * 3


def test_doi_chu_ky_tu_3600_xuong_60_khong_phai_cho_het_chu_ky_cu(monkeypatch):
    clock, ran = _Clock(), []
    long_ = WS.EventWorkerSettings(interval_seconds=3600)
    short = WS.EventWorkerSettings(interval_seconds=60)
    # đọc: đầu vòng lặp, đầu vòng 1, lần kiểm đầu tiên khi đang chờ → đã đổi sang 60 s
    _settings_seq(monkeypatch, [long_, long_, short])
    W.loop_forever(object(), _cfg(), run=lambda c, k: ran.append(clock.t) or {}, sleep=clock.sleep, clock=clock,
                   max_rounds=2)
    assert ran == [0.0, 60.0]


def test_bat_lai_thi_chay_ngay(monkeypatch):
    clock, ran = _Clock(), []
    off = WS.EventWorkerSettings(enabled=False, interval_seconds=3600)
    on = WS.EventWorkerSettings(enabled=True, interval_seconds=3600)
    _settings_seq(monkeypatch, [off, off, on])
    W.loop_forever(object(), _cfg(), run=lambda c, k: ran.append(clock.t) or {}, sleep=clock.sleep, clock=clock,
                   logf=lambda m: None, max_rounds=2)
    assert ran == [30.0]


def test_interval_dong_lenh_thang_db(monkeypatch):
    _settings_seq(monkeypatch, [WS.EventWorkerSettings(interval_seconds=3600)])
    assert W.current_settings(object(), _cfg(), fixed_interval=5).interval == 5


def test_loi_vong_worker_khong_lam_chet_vong_lap(monkeypatch):
    clock, calls = _Clock(), []
    _settings_seq(monkeypatch, [WS.EventWorkerSettings(interval_seconds=60)])

    def boom(c, k):
        calls.append(1)
        raise RuntimeError("model hỏng")
    W.loop_forever(object(), _cfg(), run=boom, sleep=clock.sleep, clock=clock, max_rounds=2)
    assert calls == [1, 1]


def test_db_doc_ghi_event_worker(pg_conn):
    assert W.current_settings(pg_conn, _cfg(300)) == W.LoopSettings(True, 300.0)
    WS.save(pg_conn, WS.EventWorkerSettings(enabled=False, interval_seconds=900))
    assert W.current_settings(pg_conn, _cfg(300)) == W.LoopSettings(False, 900.0)
