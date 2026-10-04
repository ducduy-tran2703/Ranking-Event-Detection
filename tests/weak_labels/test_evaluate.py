import pytest

from eventrank.weak_labels.evaluate import bin_of, weighted_pr


def test_trong_so_theo_kich_thuoc_tang():
    # Tầng A lớn (1000 cặp): mẫu 2 cặp, 1 dương thật, hệ thống bắt được cả hai (1 đúng, 1 sai)
    # Tầng B nhỏ (10 cặp): mẫu 2 cặp, cả 2 dương thật, hệ thống bắt cả 2
    strata = {"A": [(1, 1), (0, 1)], "B": [(1, 1), (1, 1)]}
    prec, rec = weighted_pr(strata, {"A": 1000, "B": 10})
    # TP = 500 + 10, dự đoán dương = 1000 + 10, dương thật = 500 + 10
    assert prec == pytest.approx(510 / 1010) and rec == pytest.approx(1.0)


def test_khoang_p():
    assert bin_of(0.05) == "0.00-0.10" and bin_of(0.8) == "0.80-1.00" and bin_of(1.0) == "0.80-1.00"
