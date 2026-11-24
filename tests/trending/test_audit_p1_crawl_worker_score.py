"""Kiểm tra hệ thống (P1-crawl-worker): trending/score.py — chia 0, mức nền rỗng, sự kiện 1 bài, múi giờ của mốc t."""
from datetime import UTC, datetime, timedelta

import pytest

from eventrank.trending import score as S

VN = S.VN
T = datetime(2026, 11, 23, 12, 0, tzinfo=VN)


def _arts(eid, n, sources=("a", "b"), start=T - timedelta(hours=2)):
    return [{"event_id": eid, "ts": (start + timedelta(minutes=10 * i)).timestamp(),
             "source": sources[i % len(sources)], "title": f"{eid} tin {i}"} for i in range(n)]


def test_muc_nen_rong_khong_chia_0_va_trung_binh_bang_1():
    b = S.hourly_baseline([], T - timedelta(days=30), T)
    assert b == [1.0] * 24
    assert S.window_baseline(b, T, 3) == 1.0


def test_muc_nen_khoang_rong_hoac_nguoc_van_hop_le():
    assert S.hourly_baseline([T.timestamp()], T, T) == [1.0] * 24
    assert S.hourly_baseline([T.timestamp()], T, T - timedelta(days=1)) == [1.0] * 24


def test_su_kien_1_bai_khong_vao_xu_huong_va_khong_loi():
    idx = S.EventIndex(_arts("E1", 1))
    assert S.score_at(idx, T, S.DEFAULTS, [1.0] * 24) == []


def test_su_kien_1_bai_khi_min_so_bai_1_co_diem_duong():
    idx = S.EventIndex(_arts("E1", 1, sources=("a",)))
    rows = S.score_at(idx, T, {**S.DEFAULTS, "min_so_bai": 1}, [1.0] * 24)
    assert len(rows) == 1 and rows[0]["score"] > 0 and rows[0]["tuoi_gio"] >= 0


def test_khong_co_bai_nao_tra_rong():
    assert S.score_at(S.EventIndex([]), T, S.DEFAULTS, [1.0] * 24) == []


def test_bai_sau_t_khong_ro_ri_vao_diem():
    future = [{"event_id": "E1", "ts": (T + timedelta(minutes=5)).timestamp(), "source": "c", "title": "x"}]
    a = S.score_at(S.EventIndex(_arts("E1", 3)), T, S.DEFAULTS, [1.0] * 24)
    b = S.score_at(S.EventIndex(_arts("E1", 3) + future), T, S.DEFAULTS, [1.0] * 24)
    assert a == b


def test_tat_ca_bai_chep_tieu_de_van_co_diem_duong():
    arts = [{"event_id": "E1", "ts": (T - timedelta(minutes=m)).timestamp(), "source": s, "title": "Cùng một tiêu đề"}
            for m, s in ((30, "a"), (20, "b"), (10, "c"))]
    rows = S.score_at(S.EventIndex(arts), T, S.DEFAULTS, [1.0] * 24)
    assert rows and rows[0]["n_nguon_hd"] == 1 + 0.5 + 0.5 and rows[0]["score"] > 0


def test_half_life_0_la_cau_hinh_khong_hop_le():
    """Ghi lại: half_life_hours = 0 → ZeroDivisionError (không có kiểm tra cấu hình)."""
    with pytest.raises(ZeroDivisionError):
        S.score_at(S.EventIndex(_arts("E1", 3)), T, {**S.DEFAULTS, "half_life_hours": 0}, [1.0] * 24)


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="AUDIT-P1-crawl-worker-11: window_baseline dùng t.hour theo tzinfo của t → cùng một thời "
                          "điểm truyền UTC và +07:00 cho điểm khác nhau (mọi caller hiện truyền giờ VN)")
def test_diem_khong_phu_thuoc_mui_gio_cua_t():
    b = [0.5 + h / 23 for h in range(24)]
    b = [x / (sum(b) / 24) for x in b]
    idx = S.EventIndex(_arts("E1", 4))
    vn = S.score_at(idx, T, S.DEFAULTS, b)
    utc = S.score_at(idx, T.astimezone(UTC), S.DEFAULTS, b)
    assert vn[0]["score"] == pytest.approx(utc[0]["score"])
