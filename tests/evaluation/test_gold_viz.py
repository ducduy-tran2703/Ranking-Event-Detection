import numpy as np

from eventrank.evaluation import gold_viz as gv

T0 = 1_789_000_000.0                                  # giây; chỉ cần khoảng cách thời gian


def _unit(*rows):
    E = np.array(rows, dtype=float)
    return E / np.linalg.norm(E, axis=1, keepdims=True)


def test_noi_cap_thanh_cum_bi_bac_cau():
    # a~b, b~c đủ gần nhưng a, c xa nhau → vẫn chung một cụm (lỗi bắc cầu của cách nối cặp)
    E = _unit([1, 0], [0.9, 0.44], [0.6, 0.8])
    times = np.array([T0, T0, T0])
    lab = gv.link_components(E, times, threshold=0.85)
    assert float(E[0] @ E[2]) < 0.85 and lab[0] == lab[1] == lab[2]


def test_noi_cap_bo_qua_cap_cach_qua_48h():
    E = _unit([1, 0], [1, 0.01])
    lab = gv.link_components(E, np.array([T0, T0 + 49 * 3600]), threshold=0.9)
    assert lab[0] != lab[1]


def test_quet_nguong_ngưỡng_thap_cum_lon_hon():
    E = _unit([1, 0], [0.9, 0.44], [0.6, 0.8], [0, 1])
    times = np.full(4, T0)
    gold = {0: "A", 1: "A", 2: "B", 3: "B"}
    rows = gv.sweep(E, times, gold, thresholds=[0.5, 0.85, 0.99])
    assert [r["largest"] for r in rows] == sorted((r["largest"] for r in rows), reverse=True)
    assert rows[-1]["largest"] == 1 and rows[-1]["precision"] == 1.0
    assert all(0 <= r["f1"] <= 1 for r in rows)
