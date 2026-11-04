import numpy as np

from eventrank.clustering import algorithms as al
from eventrank.evaluation.bcubed import bcubed

H = 3600.0


def _sim(groups):
    """Cosine 0,9 trong cùng nhóm, 0,1 khác nhóm, 1 trên đường chéo."""
    g = np.array(groups)
    S = np.where(g[:, None] == g[None, :], 0.9, 0.1).astype(np.float32)
    np.fill_diagonal(S, 1.0)
    return S


def test_single_pass_gom_dung_nhom_theo_nguong():
    S, t = _sim([0, 1, 0, 1]), np.array([0, 1, 2, 3]) * H
    lab = al.single_pass(S, t, th=0.5)
    assert lab[0] == lab[2] and lab[1] == lab[3] and lab[0] != lab[1]
    assert len(set(al.single_pass(S, t, th=0.95))) == 4                 # ngưỡng cao → mỗi bài một cụm


def test_single_pass_cum_nguoi_qua_cua_so_thi_mo_cum_moi():
    S, t = _sim([0, 0]), np.array([0, 60]) * H
    lab = al.single_pass(S, t, th=0.5, window_hours=48)
    assert lab[0] != lab[1]


def test_single_pass_khong_phu_thuoc_thu_tu_mang_ma_theo_thoi_gian():
    S, t = _sim([0, 1, 0]), np.array([2, 1, 0]) * H                   # bài cuối mảng đến trước
    lab = al.single_pass(S, t, th=0.5)
    assert lab[0] == lab[2] != lab[1]


def test_agglo_cat_nguong_va_cua_so():
    S, t = _sim([0, 0, 1, 1]), np.array([0, 1, 2, 3]) * H
    Z = al.agglo_tree(S, t)
    lab = al.agglo_cut(Z, 0.5)
    assert lab[0] == lab[1] != lab[2] == lab[3]
    far = al.agglo_cut(al.agglo_tree(_sim([0, 0]), np.array([0, 100]) * H), 0.5)
    assert far[0] != far[1]                                             # cùng nhóm nhưng cách 100h


def _blobs(seed, n_events=40, per=(1, 6), dim=24, noise=0.35, hours=200):
    """Vector giả: mỗi sự kiện một tâm ngẫu nhiên + nhiễu, thời gian rải trong `hours` giờ; trả (E chuẩn hoá, times)."""
    rng = np.random.default_rng(seed)
    E, T = [], []
    for _ in range(n_events):
        c, t0 = rng.normal(size=dim), rng.uniform(0, hours)
        for _ in range(rng.integers(*per)):
            E.append(c + noise * rng.normal(size=dim))
            T.append((t0 + rng.uniform(0, 30)) * H)
    E = np.array(E, dtype=np.float32)
    return E / np.linalg.norm(E, axis=1, keepdims=True), np.array(T)


def _same_partition(a, b):
    return bcubed(dict(enumerate(a)), dict(enumerate(b)))[2] == 1.0


def test_components_noi_cap_qua_nguong_va_trong_cua_so():
    E = np.array([[1, 0], [1, 0], [0, 1], [1, 0]], dtype=np.float32)
    t = np.array([0, 10, 5, 100]) * H                                  # bài 3 giống bài 0 nhưng cách 100h
    comp = al.components(E, t, th=0.9, window_hours=48, block=2)       # block nhỏ: thử nối giữa các khối
    assert comp[0] == comp[1] and len({comp[0], comp[2], comp[3]}) == 3


def test_agglo_components_giong_het_agglo_day_du():
    for seed in range(5):
        E, t = _blobs(seed)
        for th in (0.6, 0.75, 0.85):
            full = al.agglo_cut(al.agglo_tree(E @ E.T, t, 48), th)
            comp, stats = al.agglo_components(E, t, th, 48)
            assert _same_partition(comp, full), (seed, th)
            assert stats["n_clusters"] == len(set(comp)) == comp.max() + 1


def test_agglo_components_bao_loi_khi_thanh_phan_qua_lon():
    E = np.ones((5, 2), dtype=np.float32) / np.sqrt(2)
    try:
        al.agglo_components(E, np.zeros(5), 0.5, max_component=3)
    except ValueError as e:
        assert "thành phần" in str(e)
    else:
        raise AssertionError("phải báo lỗi")
