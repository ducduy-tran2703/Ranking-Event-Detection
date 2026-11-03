import csv
import math
from datetime import datetime

import pytest

from eventrank.trending import score as S

CFG = {**S.DEFAULTS, "min_so_bai": 1, "top_k": 5, "top_n_hours": 1}


def _a(eid, t, source="vnexpress", title=""):
    return {"event_id": eid, "ts": datetime.fromisoformat(t).timestamp(), "source": source,
            "title": title or f"{eid} {source} {t}"}


def T(s):
    return datetime.fromisoformat(s)


ARTS = [_a("E1", "2026-09-15T08:00:00+07:00", "vnexpress"), _a("E1", "2026-09-15T09:30:00+07:00", "tuoitre"),
        _a("E1", "2026-09-15T10:00:00+07:00", "tuoitre"), _a("E2", "2026-09-15T09:00:00+07:00", "nhandan")]
FUTURE = [_a("E1", "2026-09-15T10:00:01+07:00", "thanhnien"), _a("E1", "2026-09-15T11:00:00+07:00", "vietnamnet"),
          _a("E3", "2026-09-15T10:30:00+07:00", "vnexpress"), _a("E2", "2026-09-16T08:00:00+07:00", "tuoitre")]
B = [1.0] * 24


def test_khong_ro_ri_tuong_lai():
    """Thêm bài đăng SAU t (cùng sự kiện hoặc sự kiện mới) không được đổi điểm tại t."""
    t = T("2026-09-15T10:00:00+07:00")
    before = S.score_at(S.EventIndex(ARTS), t, CFG, B)
    after = S.score_at(S.EventIndex(ARTS + FUTURE), t, CFG, B)
    assert before == after and {r["event_id"] for r in before} == {"E1", "E2"}


def test_dac_trung_va_cong_thuc():
    t = T("2026-09-15T10:00:00+07:00")
    rows = {r["event_id"]: r for r in S.score_at(S.EventIndex(ARTS + FUTURE), t, {**CFG, "formula": "gravity"}, B)}
    e1 = rows["E1"]
    # cửa sổ (07:00, 10:00]: cả 3 bài E1 (bài 10:00 tính, bài 10:00:01 không)
    assert (e1["so_bai_den_t"], e1["so_bai_3h"], e1["so_bao"], e1["tuoi_gio"]) == (3, 3, 2, 2.0)
    assert e1["score"] == pytest.approx(2 ** 1.0 * math.log1p(3) / 4 ** 1.5)
    assert S.score_at(S.EventIndex(ARTS), T("2026-09-15T13:00:01+07:00"), CFG, B) == []   # hết cửa sổ → không xếp


def test_min_so_bai_va_bai_chep():
    t = T("2026-09-15T10:00:00+07:00")
    arts = [_a("E1", "2026-09-15T09:00:00+07:00", "vnexpress", "Bão số 5 vào bờ"),
            _a("E1", "2026-09-15T09:10:00+07:00", "nhandan", "Bão số 5 vào bờ!"),      # chép tiêu đề báo khác
            _a("E2", "2026-09-15T09:30:00+07:00", "tuoitre", "Giá vàng")]
    rows = S.score_at(S.EventIndex(arts), t, {**CFG, "min_so_bai": 2}, B)
    assert [r["event_id"] for r in rows] == ["E1"] and rows[0]["n_nguon_hd"] == 1.5 and rows[0]["so_bao"] == 2


def test_muc_nen_theo_gio():
    ts = [T(f"2026-09-15T{h:02d}:10:00+07:00").timestamp() for h in (9, 9, 9, 3)]
    b = S.hourly_baseline(ts, S.day("2026-09-15"), S.day("2026-09-16"))
    assert sum(b) / 24 == pytest.approx(1.0) and b[9] == pytest.approx(4 / (28 / 24))
    assert S.window_baseline(b, T("2026-09-15T10:00:00+07:00"), 3) == pytest.approx((b[9] + b[8] + b[7]) / 3)


def test_compute_va_run(tmp_path):
    res = S.compute(ARTS, CFG, T("2026-09-15T08:00:00+07:00"), T("2026-09-15T12:00:00+07:00"), log=lambda s: None)
    assert res["meta"]["n_steps"] == 4
    assert [r["t"][11:16] for r in res["xu_huong"] if r["hang"] == 1] == ["09:00", "10:00", "11:00", "12:00"]
    assert {r["phuong_phap"] for r in res["moc"]} == {"so_bai", "so_bao", "so_bai_3h"}
    d = {r["event_id"]: r for r in res["diem"]}
    assert set(d) == {"E1", "E2"} and d["E1"]["so_gio_trong_top10"] >= 1
    assert [r["event_id"] for r in res["diem"]] == sorted(d, key=lambda e: -d[e]["tong_diem"])   # xếp theo tổng điểm
    ev = tmp_path / "ev"
    ev.mkdir()
    with open(ev / "bai_su_kien.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "article_id", "published_at", "source", "category", "title", "is_medoid"])
        for i, a in enumerate(ARTS):
            w.writerow([a["event_id"], f"id{i}", datetime.fromtimestamp(a["ts"], S.VN).isoformat(), a["source"], "",
                        a["title"], 0])
    S.run(ev, {**CFG, "baseline_start": "2026-09-15", "baseline_end": "2026-09-16"}, tmp_path / "o",
          "2026-09-15", "2026-09-16", log=lambda s: None)
    with open(tmp_path / "o" / "xu_huong.csv", encoding="utf-8") as f:
        xu = list(csv.DictReader(f))
    assert list(xu[0]) == S.XU_FIELDS and xu[0]["event_id"] == "E1"
    assert (tmp_path / "o" / "diem_su_kien.csv").exists() and (tmp_path / "o" / "xu_huong_moc.csv").exists()


def test_cong_thuc_decay():
    """t2: v = Σ 2^(−(t − t_i)/H) trên bài ≤ t, không phạt tuổi sự kiện."""
    t = T("2026-09-15T10:00:00+07:00")
    rows = {r["event_id"]: r for r in S.score_at(S.EventIndex(ARTS + FUTURE), t, CFG, B)}
    v = 2 ** (-2 / 3) + 2 ** (-0.5 / 3) + 1                         # bài 08:00, 09:30, 10:00 (bài sau t bị bỏ)
    assert rows["E1"]["van_toc"] == pytest.approx(v)
    assert rows["E1"]["score"] == pytest.approx(2 * math.log1p(v))
    with pytest.raises(ValueError, match="formula"):
        S.score_at(S.EventIndex(ARTS), t, {**CFG, "formula": "khac"}, B)


def test_muc_nen_di_vao_diem():
    """b_W ≠ 1 phải đổi điểm: giờ vắng (b nhỏ) → điểm cao hơn giờ đông, cùng số bài."""
    t = T("2026-09-15T10:00:00+07:00")
    idx = S.EventIndex(ARTS)
    low, high = [1.0] * 24, [1.0] * 24
    for h in (7, 8, 9):
        low[h], high[h] = 0.5, 2.0
    for formula in ("decay", "gravity"):
        c = {**CFG, "formula": formula}
        s1 = {r["event_id"]: r["score"] for r in S.score_at(idx, t, c, B)}
        s_low = {r["event_id"]: r["score"] for r in S.score_at(idx, t, c, low)}
        s_high = {r["event_id"]: r["score"] for r in S.score_at(idx, t, c, high)}
        assert s_low["E1"] > s1["E1"] > s_high["E1"], formula


def test_decay_su_kien_lon_dang_nong_dung_dau():
    """Ca của báo cáo kiểm tra: sự kiện lâu đời nhưng đang có nhiều bài/3h phải thắng sự kiện mới 2 bài."""
    t = T("2026-09-15T22:00:00+07:00")
    big = [_a("BIG", f"2026-09-1{d}T{h:02d}:00:00+07:00", s) for d, h, s in
           [(4, 8, "a"), (4, 12, "b"), (5, 9, "c")] + [(5, 19 + k % 3, "abcdef"[k % 6]) for k in range(15)]]
    new = [_a("NEW", "2026-09-15T21:00:00+07:00", "a"), _a("NEW", "2026-09-15T21:30:00+07:00", "b")]
    rows = S.score_at(S.EventIndex(big + new), t, CFG, B)
    assert rows[0]["event_id"] == "BIG"
    grav = S.score_at(S.EventIndex(big + new), t, {**CFG, "formula": "gravity"}, B)
    assert grav[0]["event_id"] == "NEW"                                # t1 xếp ngược — lý do đổi công thức
