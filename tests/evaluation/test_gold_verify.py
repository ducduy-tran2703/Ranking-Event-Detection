import numpy as np
import pytest

from eventrank.evaluation import gold_verify as gv


def _arts(n):
    return [{"stt": i + 1, "id": f"a{i}", "t": "2026-09-14T08:00:00+07:00", "source": "tuoitre",
             "title": f"bài {i}", "sapo": ""} for i in range(n)]


PROP = [{"members": [0, 1, 2], "clusters": [{"name": "A", "members": [0, 1, 2], "confidence": "cao"}], "x": []},
        {"members": [3, 4], "clusters": [{"name": "B", "members": [3], "confidence": "thấp"},
                                         {"name": "C", "members": [4], "confidence": "cao"}], "x": []},
        {"members": [5], "clusters": [{"name": "", "members": [5], "confidence": "cao"}], "x": []}]


def test_danh_sach_cum_on_dinh_theo_bai_dau():
    cl = gv.cluster_list(PROP)
    assert [c["id"] for c in cl] == ["K0001", "K0002", "K0003", "K0004"]
    assert [c["members"] for c in cl] == [[0, 1, 2], [3], [4], [5]]


def test_ung_vien_gop_chi_cap_cum_khac_nhau_gan_nhau():
    E = np.array([[1, 0], [1, 0], [1, 0], [0.8, 0.6], [0, 1], [0.79, 0.61]], dtype=float)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    times = np.zeros(6)
    pairs = gv.merge_candidates(gv.cluster_list(PROP), E, times, threshold=0.9)
    keys = {(p["a"], p["b"]) for p in pairs}
    assert ("K0002", "K0004") in keys                 # bài 3 ↔ bài 5 rất gần, khác cụm
    assert all(p["a"] != p["b"] for p in pairs) and ("K0001", "K0003") not in keys


def test_ap_ket_qua_tach_loai_va_gop():
    cl = gv.cluster_list(PROP)
    verdicts = {"K0001": {"groups": [{"name": "A1", "members": [1, 2], "confidence": "cao"},
                                     {"name": "A2", "members": [3], "confidence": "cao"}], "x": []}}
    merges = {"K0002|K0004": {"gop": True}, "K0001|K0003": {"gop": False}}
    final, log = gv.apply(_arts(6), cl, verdicts, merges)
    groups = sorted(sorted(c["members"]) for c in final)
    assert groups == [[0, 1], [2], [3, 5], [4]]
    assert any("tách" in line for line in log) and any("gộp" in line for line in log)


def test_ap_ket_qua_bao_loi_khi_kiem_cum_lam_mat_bai():
    cl = gv.cluster_list(PROP)
    with pytest.raises(ValueError, match="K0001"):
        gv.apply(_arts(6), cl, {"K0001": {"groups": [{"name": "A", "members": [1, 2]}], "x": []}}, {})


def test_quy_tac_gan_lay_dung_doan_trong_tai_lieu_tong_hop():
    """Prompt agent chép mục 4.8.1–4.8.7 của docs/tong-hop.md: đổi tiêu đề mà quên sửa hằng → test này đỏ."""
    rules = gv._rules()
    assert rules.startswith(gv.RULES_START)
    assert "Mức 3" in rules and "R1" in rules and "R6" in rules
    assert gv.RULES_END not in rules
    assert "Gán tay (cho người)" not in rules
