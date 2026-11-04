import numpy as np

from eventrank.evaluation import cluster_eval as ce
from eventrank.evaluation.bcubed import bcubed


def test_per_item_khop_bcubed():
    pred = np.array([1, 1, 2, 2, 3], dtype=object)
    gold = np.array(["a", "a", "a", "b", "b"], dtype=object)
    idx = np.arange(5)
    P, R = ce.per_item(pred, gold, idx)
    p, r, f = bcubed(dict(enumerate(pred)), dict(enumerate(gold)))
    assert np.isclose(P.mean(), p) and np.isclose(R.mean(), r) and np.isclose(ce.f1(P, R), f)


def test_purity_va_inverse_purity():
    pred, gold = np.array([1, 1, 1, 2]), np.array(["a", "a", "b", "b"])
    assert ce.purity(pred, gold) == 0.75
    assert ce.purity(gold, pred) == 0.75
    one = np.arange(4)
    assert ce.purity(one, gold) == 1.0                                  # mỗi bài một cụm: purity 1 nhưng inverse thấp
    assert ce.purity(gold, one) == 0.5


def test_boot_weights_theo_cum_vang():
    gold = np.array(["a", "a", "b", "c"], dtype=object)
    W = ce.boot_weights(gold, np.arange(4), n_boot=50, seed=1)
    assert W.shape == (50, 4)
    assert (W[:, 0] == W[:, 1]).all()                                  # bài cùng cụm vàng luôn cùng trọng số
    assert (W.sum(1) >= 0).all()


def test_delta_cung_cau_hinh_bang_0_va_score_co_ci():
    gold = np.array(["a", "a", "b", "b", "c"], dtype=object)
    idx = np.arange(5)
    W = ce.boot_weights(gold, idx, n_boot=30)
    good = ce.score(np.array([0, 0, 1, 1, 2]), gold, idx, W)
    bad = ce.score(np.arange(5), gold, idx, W)
    assert good["f1"] == 1.0 and good["ami"] > 0.99 and good["f1_ci95"][0] <= 1.0
    d = ce.delta(bad, good)
    assert d["delta"] > 0 and ce.delta(good, good)["ci95"] == [0.0, 0.0]


def test_errors_tim_gop_nham_va_tach_nham():
    arts = [{"stt": i + 1, "source": "s", "t": "2026-09-15T08:00", "title": f"b{i}"} for i in range(4)]
    gold = np.array(["a", "a", "b", "c"], dtype=object)
    pred = np.array([0, 1, 2, 2])
    rows = ce.errors(pred, gold, np.arange(4), arts)
    assert {r["loai"] for r in rows} == {"gop_nham", "tach_nham"}


def test_lexical_tiers_chia_ba():
    gold = np.array(["a", "a", "b", "b", "c", "c", "d"], dtype=object)
    St = np.eye(7)
    for (i, j), v in {(0, 1): 0.1, (2, 3): 0.5, (4, 5): 0.9}.items():
        St[i, j] = St[j, i] = v
    tier = ce.lexical_tiers(St, gold, np.arange(7))
    assert tier == {"a": "thấp", "b": "vừa", "c": "cao"}
