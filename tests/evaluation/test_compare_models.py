import numpy as np

from eventrank.evaluation import compare_models as cm


def test_auc_thu_tu_dung_bang_1_hoa_bang_nua():
    L = np.array([3, 3, 2, 2])
    assert cm.auc(np.array([0.9, 0.8, 0.5, 0.4]), L, 3, 2) == 1.0
    assert cm.auc(np.array([0.5, 0.5, 0.5, 0.5]), L, 3, 2) == 0.5
    assert np.isnan(cm.auc(np.array([0.9, 0.8, 0.5, 0.4]), L, 1, 0))


def test_average_precision():
    assert cm.average_precision(np.array([0.9, 0.8, 0.1]), np.array([1, 1, 0])) == 1.0
    # dương đứng thứ 2 → precision tại đó 1/2
    assert cm.average_precision(np.array([0.9, 0.8, 0.1]), np.array([0, 1, 0])) == 0.5


def test_nguong_f1_tot_nhat_tach_dung_hai_nhom():
    s = np.array([0.95, 0.9, 0.85, 0.3, 0.2])
    assert cm.best_threshold(s, np.array([1, 1, 1, 0, 0])) == 0.85


def test_metrics_recall_va_gop_nham_o_nguong_chon_tren_test():
    st, Lt = np.array([0.9, 0.8, 0.5, 0.2]), np.array([3, 3, 2, 0])      # ngưỡng = 0,8
    sh, Lh = np.array([0.85, 0.6, 0.82, 0.1]), np.array([3, 3, 2, 1])
    m = cm.metrics(st, Lt, sh, Lh)
    assert m["threshold"] == 0.8
    assert m["recall_hard"] == 0.5 and m["false_merge_hard"] == 0.5


def test_bootstrap_ghep_cap_cung_mo_hinh_thi_delta_bang_0():
    rng = np.random.default_rng(1)
    Lt, Lh = rng.integers(0, 4, 60), rng.integers(0, 4, 30)
    s = (Lt / 3 + rng.normal(0, 0.3, 60), Lh / 3 + rng.normal(0, 0.3, 30))
    out = cm.paired_bootstrap(s, s, Lt, Lh, n_boot=20)
    assert all(v["delta"] == 0 and v["ci95"] == [0, 0] for v in out.values())


def test_bootstrap_mo_hinh_tot_hon_co_delta_auc_duong():
    rng = np.random.default_rng(2)
    Lt, Lh = rng.integers(0, 4, 200), rng.integers(0, 4, 80)
    noise = lambda n, sd: rng.normal(0, sd, n)
    weak = (Lt / 3 + noise(200, 1.0), Lh / 3 + noise(80, 1.0))
    good = (Lt / 3 + noise(200, 0.1), Lh / 3 + noise(80, 0.1))
    out = cm.paired_bootstrap(weak, good, Lt, Lh, n_boot=50)
    assert out["auc_3v2"]["delta"] > 0 and out["auc_3v2"]["ci95"][0] > 0
    assert out["spearman"]["delta"] > 0


def test_parse_model_tien_xu_ly_mac_dinh_va_duong_dan_hf():
    m = cm.parse_model("e5_zs=intfloat/multilingual-e5-base:query")
    assert m == {"name": "e5_zs", "path": "intfloat/multilingual-e5-base", "prep": "query"}
    assert cm.parse_model("x=org/model")["prep"] == "pyvi"


def test_load_pairs_bo_train_doc_van_ban(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("﻿split,a,b,level,text_a,text_b\n"
                 "train,x,y,3,X,Y\ntest,a,b,3,A,B\ntest_hard,a,c,1,A,C\n", encoding="utf-8")
    d = cm.load_pairs(f)
    assert set(d) == {"test", "test_hard"}
    assert d["test_hard"]["text"] == {"a": "A", "c": "C"} and list(d["test"]["level"]) == [3]
