import numpy as np

from eventrank.weak_labels.label_model import ABSTAIN, LabelModel


def _synthetic(n=4000, seed=0):
    """3 hàm tốt (90%) + 1 hàm kém (60%), mỗi hàm bỏ phiếu ở 70% số cặp."""
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.3).astype(int)
    cols = []
    for acc in (0.9, 0.9, 0.9, 0.6):
        vote = np.where(rng.random(n) < acc, y, 1 - y)
        vote = np.where(rng.random(n) < 0.7, vote, ABSTAIN)
        cols.append(vote)
    return np.stack(cols, axis=1), y


def test_label_model_chinh_xac_hon_ham_kem_nhat_va_uoc_luong_duoc_do_chinh_xac():
    L, y = _synthetic()
    lm = LabelModel().fit(L)
    p = lm.predict_proba(L)
    acc = ((p > 0.5).astype(int) == y).mean()
    assert acc > 0.9
    est = lm.accuracies()
    assert est[:3].min() > est[3]            # nhận ra hàm số 4 kém hơn
    assert abs(lm.prior - 0.3) < 0.05


def test_bo_qua_khong_phu_thuoc_lop_thi_cap_khong_phieu_xap_xi_prior():
    # Trong dữ liệu giả lập, tỉ lệ bỏ qua (30%) như nhau ở hai lớp → im lặng gần như không mang thông tin
    L, _ = _synthetic()
    lm = LabelModel().fit(L)
    p = lm.predict_proba(np.full((1, 4), ABSTAIN))
    assert abs(p[0] - lm.prior) < 0.03


def test_ham_chi_bo_phieu_mot_chieu_van_hoc_duoc():
    rng = np.random.default_rng(1)
    n = 3000
    y = (rng.random(n) < 0.4).astype(int)
    pos_only = np.where((y == 1) & (rng.random(n) < 0.6), 1, ABSTAIN)
    neg_only = np.where((y == 0) & (rng.random(n) < 0.6), 0, ABSTAIN)
    mixed = np.where(rng.random(n) < 0.85, y, 1 - y)
    L = np.stack([pos_only, neg_only, mixed], axis=1)
    p = LabelModel().fit(L).predict_proba(L)
    assert ((p > 0.5).astype(int) == y).mean() > 0.88


def test_prior_co_dinh_khong_bi_em_thay_doi():
    L, _ = _synthetic()
    lm = LabelModel(prior=0.1).fit(L)
    assert lm.prior == 0.1


def test_cap_khong_co_phieu_duong_nao_khong_duoc_coi_la_duong():
    # Tái hiện lỗi trên dữ liệu thật: LF âm một chiều im lặng → EM đẩy cặp không có bằng chứng lên p ≈ 1
    rng = np.random.default_rng(2)
    n = 5000
    y = (rng.random(n) < 0.15).astype(int)
    pos_only = np.where((y == 1) & (rng.random(n) < 0.5), 1, ABSTAIN)
    neg_a = np.where((y == 0) & (rng.random(n) < 0.4), 0, ABSTAIN)
    neg_b = np.where((y == 0) & (rng.random(n) < 0.4), 0, ABSTAIN)
    L = np.stack([pos_only, neg_a, neg_b], axis=1)
    p = LabelModel().fit(L).predict_proba(L)
    assert p[(L != 1).all(1)].max() <= 0.5
