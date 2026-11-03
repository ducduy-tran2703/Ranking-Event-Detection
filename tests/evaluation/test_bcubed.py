import pytest

from eventrank.evaluation.bcubed import bcubed


def test_hai_cach_gom_giong_nhau_dat_1():
    gold = {"a": 1, "b": 1, "c": 2}
    pred = {"a": "x", "b": "x", "c": "y"}           # tên cụm khác nhau không quan trọng
    assert bcubed(pred, gold) == pytest.approx((1.0, 1.0, 1.0))


def test_moi_bai_mot_cum_thi_precision_1_recall_thap():
    gold = {i: 0 for i in "abcd"}
    pred = {i: i for i in "abcd"}
    p, r, f = bcubed(pred, gold)
    assert (p, r) == pytest.approx((1.0, 0.25))
    assert f == pytest.approx(0.4)


def test_gop_tat_ca_thi_recall_1_precision_thap():
    gold = {i: i for i in "abcd"}
    pred = {i: 0 for i in "abcd"}
    assert bcubed(pred, gold)[:2] == pytest.approx((0.25, 1.0))


def test_vi_du_tinh_tay():
    # vàng {a,b,c} {d,e}; dự đoán {a,b} {c,d,e}
    # P: a 1, b 1, c 1/3, d 2/3, e 2/3 → 11/15 ; R: a 2/3, b 2/3, c 1/3, d 1, e 1 → 11/15
    gold = {"a": 1, "b": 1, "c": 1, "d": 2, "e": 2}
    pred = {"a": 1, "b": 1, "c": 2, "d": 2, "e": 2}
    assert bcubed(pred, gold) == pytest.approx((11 / 15, 11 / 15, 11 / 15))


def test_chi_tinh_tren_bai_co_o_ca_hai_ben():
    gold = {"a": 1, "b": 1}
    pred = {"a": 1, "b": 1, "z": 9}                 # z không có trong vàng → bỏ qua
    assert bcubed(pred, gold) == pytest.approx((1.0, 1.0, 1.0))


def test_khong_co_bai_chung_thi_bao_loi():
    with pytest.raises(ValueError):
        bcubed({"a": 1}, {"b": 1})
