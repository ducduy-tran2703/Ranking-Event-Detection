import numpy as np

from eventrank.weak_labels.label_model import ABSTAIN
from eventrank.weak_labels.lfs import VETO_P, apply_vetoes, lf_entity_overlap, lf_head_entities
from eventrank.weak_labels.pairs import FEATURES, numbers, title_dates


def _f(**kw):
    f = {k: np.zeros(1) for k in FEATURES}
    for k, v in kw.items():
        f[k] = np.array([v], dtype=float)
    return f


def test_ngay_trong_tieu_de():
    assert title_dates("Giá Bitcoin hôm nay 8.9.2026: cá voi thức giấc") == {(8, 9)}
    assert title_dates("Tối 10-9, giá vàng giảm sâu") == {(10, 9)}
    assert title_dates("Không khí Quốc khánh 2/9 rộn ràng") == set()     # ngày lễ, không phải ngày đăng
    assert title_dates("Thắng 2-1 trên sân nhà") == set()                 # tỉ số không phải ngày
    assert title_dates("Tỉ số 13-14 kịch tính") == set()                  # tháng 14 không tồn tại
    # Lỗi v1: chữ "ngày" bị coi là ngữ cảnh ngày lễ → bỏ sót chuỗi bài theo ngày
    assert title_dates("Giá vàng ngày 16/9: vàng miếng bật tăng") == {(16, 9)}
    assert title_dates("Chứng khoán ngày 17/9: cổ phiếu ngân hàng") == {(17, 9)}
    assert title_dates("Ngày Quốc khánh 2/9 rộn ràng") == set()


def test_chuoi_bai_theo_ngay_khac_ngay_bi_phu_quyet_du_tf_idf_rat_cao():
    # "Lịch thi đấu hôm nay 31/8" vs "… 29/8": label model cho p≈1 vì tiêu đề gần như y hệt
    p = np.array([0.999])
    assert apply_vetoes(_f(date_conflict=1, cos_head=0.9), p)[0] == VETO_P
    assert apply_vetoes(_f(date_conflict=0, cos_head=0.9), p)[0] == 0.999


def test_phieu_duong_chi_khi_gan_nhau_ve_thoi_gian():
    strong = {"ent_wjacc": 0.5, "ent_score": 30, "n_head_shared": 3}
    assert lf_entity_overlap(_f(dt_hours=10, **strong))[0] == 1
    assert lf_entity_overlap(_f(dt_hours=120, **strong))[0] == ABSTAIN
    assert lf_head_entities(_f(dt_hours=10, **strong))[0] == 1
    assert lf_head_entities(_f(dt_hours=120, **strong))[0] == ABSTAIN


def test_con_so_kem_don_vi():
    assert numbers("Lũ quét làm 15 người chết, thiệt hại 2,5 tỷ đồng") == {"15 người", "2.5 tỷ"}
    assert numbers("Năm 2026 có nhiều đổi mới") == set()
