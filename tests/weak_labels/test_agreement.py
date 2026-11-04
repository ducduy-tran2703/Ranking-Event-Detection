import csv

import pytest

from eventrank.weak_labels.agreement import cohen_kappa, compare


def test_kappa_dong_thuan_hoan_toan_bang_1():
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == pytest.approx(1.0)


def test_kappa_tru_phan_dong_thuan_do_ngau_nhien():
    # 80% trùng nhau, nhưng đã có 50% trùng do ngẫu nhiên → κ = (0.8 - 0.5) / (1 - 0.5) = 0.6
    a = [1] * 5 + [0] * 5
    b = [1, 1, 1, 1, 0, 0, 0, 0, 0, 1]
    assert cohen_kappa(a, b) == pytest.approx(0.6)


def _write(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_so_sanh_bo_qua_o_trong_va_dau_hoi(tmp_path):
    human, llm = tmp_path / "h.csv", tmp_path / "l.csv"
    _write(human, [{"pair_no": "1", "label_human": "1"}, {"pair_no": "2", "label_human": " 0 "},
                   {"pair_no": "3", "label_human": ""}, {"pair_no": "4", "label_human": "?"}],
           ["pair_no", "label_human"])
    _write(llm, [{"pair_no": str(i), "label_llm": "1", "p": "0.9"} for i in range(1, 5)],
           ["pair_no", "label_llm", "p"])
    res = compare(human, llm)
    assert res["n"] == 2 and res["agree"] == 1
    assert [d["pair_no"] for d in res["disagreements"]] == ["2"]
