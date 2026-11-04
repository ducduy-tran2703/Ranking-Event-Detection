import numpy as np

from eventrank.weak_labels.build import Calibrator, gate


def test_cap_cung_bao_can_hai_nhom_bang_chung_khac_bao_chi_can_mot():
    p_raw = np.array([0.99, 0.99, 0.99, 0.99])
    n_fam = np.array([1, 1, 2, 1])
    cross = np.array([1, 0, 0, 0])
    same_dup = np.array([0, 0, 0, 1])
    veto = np.zeros(4, bool)
    p = gate(p_raw, n_fam, cross, same_dup, veto, min_families=1, min_families_same_source=2)
    assert p.tolist() == [0.99, 0.5, 0.99, 0.99]     # bài đăng lại thì một bằng chứng là đủ


def test_phu_quyet_ha_p_xuong_thap():
    p = gate(np.array([0.99]), np.array([3]), np.array([1]), np.array([0]), np.array([True]),
             min_families=1, min_families_same_source=2)
    assert p[0] <= 0.02


def test_hieu_chinh_dua_diem_ve_ti_le_that_va_tach_cung_khac_bao():
    rng = np.random.default_rng(0)
    score = np.full(400, 0.99)
    cross = np.array([0] * 200 + [1] * 200)
    y = np.concatenate([rng.random(200) < 0.5, rng.random(200) < 0.9]).astype(int)
    p = Calibrator(min_group=60).fit(score, cross, y).transform(score, cross)
    assert abs(p[:200].mean() - 0.5) < 0.1 and abs(p[200:].mean() - 0.9) < 0.1


def _feats(n, cos):
    from eventrank.weak_labels.pairs import FEATURES
    f = {k: np.zeros(n) for k in FEATURES}
    f["cos_dense"] = np.full(n, np.nan)
    f["cos_lead"] = np.array(cos, float)
    return f


def test_negative_kho_khong_duoc_giong_anchor_hon_positive():
    from eventrank.weak_labels.build import select_training
    # anchor 0, positive 1 (cos 0.14). Ứng viên âm: 2 (cos 0.145 — giống anchor hơn cả positive → có thể là
    # dương bị bỏ sót), 4 (cos 0.12 nhưng cùng sự kiện với positive qua cặp 1–4), 3 (cos 0.10 → hợp lệ)
    pairs = np.array([[0, 1], [0, 2], [0, 3], [0, 4], [1, 4]])
    p = np.array([0.9, 0.05, 0.05, 0.05, 0.9])
    feats = _feats(5, [0.14, 0.145, 0.10, 0.12, 0.5])
    split = ["train"] * 5
    triplets, _ = select_training(None, pairs, p, feats, split, pos_th=0.8, neg_th=0.1,
                                  max_pos_per_anchor=3, neg_ratio=3, seed=0, neg_margin=0.95)
    by_anchor = {(i, j): c for i, j, c, _ in triplets}
    assert by_anchor[(0, 1)] == 3


def test_negative_phai_khac_ve_noi_dung_khong_chi_vi_cach_xa_thoi_gian():
    from eventrank.weak_labels.build import select_training
    # Ứng viên 2: p thấp CHỈ vì cách anchor > 72h, nhưng nội dung rất giống (cos 0.40, wjacc 0.25)
    # → thường là tin tiếp nối của CÙNG sự kiện (đo: 29% negative khó kiểu này là cùng sự kiện).
    # Ứng viên 3: khác rõ cả từ vựng (cos 0.10) lẫn thực thể (wjacc 0.05) → negative hợp lệ.
    # Ứng viên 4: từ vựng khác (cos 0.10) nhưng chung nhiều thực thể (wjacc 0.30) → có thể là khía cạnh khác
    # của cùng một sự kiện lớn (chuyến thăm nhiều ngày) → không dùng.
    pairs = np.array([[0, 1], [0, 2], [0, 3], [0, 4]])
    p = np.array([0.9, 0.0, 0.0, 0.0])
    feats = _feats(4, [0.6, 0.40, 0.10, 0.11])
    feats["ent_wjacc"] = np.array([0.5, 0.25, 0.05, 0.30])
    triplets, soft = select_training(None, pairs, p, feats, ["train"] * 5, pos_th=0.8, neg_th=0.1,
                                     max_pos_per_anchor=3, neg_ratio=3, seed=0, neg_margin=0.95)
    assert triplets[0][2] == 3
    assert {(i, j) for i, j, s in soft if s <= 0.1} == {(0, 3)}


def test_negative_khong_duoc_giong_ve_nghia_khi_co_embedding():
    from eventrank.weak_labels.build import select_training
    # Ứng viên 2: khác từ vựng & thực thể nhưng cos ngữ nghĩa 0.75 → kiểu "cùng nghĩa, khác chữ" (dương bị sót)
    # Ứng viên 3: khác cả nghĩa (0.30) → negative hợp lệ
    pairs = np.array([[0, 1], [0, 2], [0, 3]])
    p = np.array([0.9, 0.0, 0.0])
    feats = _feats(3, [0.5, 0.10, 0.10])
    feats["cos_dense"] = np.array([0.9, 0.75, 0.30])
    triplets, soft = select_training(None, pairs, p, feats, ["train"] * 4, pos_th=0.8, neg_th=0.1,
                                     max_pos_per_anchor=3, neg_ratio=3, seed=0, neg_margin=0.95,
                                     neg_max_dense=0.55)
    assert triplets[0][2] == 3
    assert {(i, j) for i, j, s in soft if s <= 0.1} == {(0, 3)}


def test_dat_nguong_ngu_nghia():
    from eventrank.weak_labels import lfs
    from eventrank.weak_labels.label_model import ABSTAIN
    old = (lfs.DENSE_POS, lfs.DENSE_NEG)
    try:
        lfs.set_dense_thresholds(0.8, 0.3)
        f = _feats(3, [0, 0, 0])
        f["dt_hours"] = np.array([5.0, 5.0, 5.0])
        f["cos_dense"] = np.array([0.85, 0.5, 0.2])
        assert lfs.lf_dense(f).tolist() == [1, ABSTAIN, 0]
    finally:
        lfs.set_dense_thresholds(*old)


def test_chi_co_bang_chung_ngu_nghia_thi_khong_duoc_la_cap_duong():
    # Đo trên 45 cặp mới chỉ có phiếu ngữ nghĩa: 26 đúng (58%) — thường là "cùng khuôn tin, khác đối tượng"
    # (điểm chuẩn hai trường khác nhau). Có thêm thực thể/từ vựng thì 47/50 đúng.
    p_raw = np.array([0.95, 0.95])
    n_fam = np.array([1, 2])
    semantic_only = np.array([True, False])
    p = gate(p_raw, n_fam, np.array([1, 1]), np.array([0, 0]), np.zeros(2, bool), min_families=1,
             min_families_same_source=2, semantic_only=semantic_only)
    assert p.tolist() == [0.5, 0.95]


def test_nhan_ra_cap_chi_co_phieu_ngu_nghia():
    from eventrank.weak_labels.label_model import ABSTAIN
    from eventrank.weak_labels.lfs import LFS, only_semantic
    names = [lf.__name__ for lf in LFS]
    L = np.full((3, len(LFS)), ABSTAIN)
    L[0, names.index("lf_dense")] = 1
    L[1, names.index("lf_dense")] = 1
    L[1, names.index("lf_lexical")] = 1
    L[2, names.index("lf_dense")] = 1
    L[2, names.index("lf_time_far")] = 0                      # phiếu âm không tính là bằng chứng dương
    assert only_semantic(L).tolist() == [True, False, True]


def test_hieu_chinh_khong_duoc_mo_khoa_cap_da_bi_chan():
    # Lỗi đã gặp: cặp bị chặn có điểm 0,5 → isotonic ánh xạ 0,5 thành 0,68 → lọt vào tầng mở rộng (p ≥ 0,6)
    from eventrank.weak_labels.build import finalize
    p_cal = np.array([0.68, 0.68, 0.9, 0.9])
    gated = np.array([True, False, False, False])
    veto = np.array([False, False, True, False])
    assert finalize(p_cal, gated, veto).tolist() == [0.5, 0.68, 0.02, 0.9]
