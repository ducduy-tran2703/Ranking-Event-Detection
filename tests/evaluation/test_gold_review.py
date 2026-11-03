import json
import re

import numpy as np
import pytest

from eventrank.evaluation import gold_review as gr


def _arts(times):
    return [{"stt": i + 1, "id": f"a{i}", "t": t, "source": "tuoitre", "title": f"bài {i}", "sapo": ""}
            for i, t in enumerate(times)]


def test_gom_tho_noi_cap_giong_va_tach_cap_xa_qua_48h():
    arts = _arts(["2026-09-14T08:00:00+07:00", "2026-09-14T09:00:00+07:00", "2026-09-17T09:00:00+07:00",
                  "2026-09-14T10:00:00+07:00"])
    T = np.zeros((4, 4)); M = np.eye(4)
    T[0, 1] = T[1, 0] = 0.5                       # giống về chữ
    M[0, 2] = M[2, 0] = 0.9                       # giống nghĩa nhưng cách 73h → không nối
    M[1, 3] = M[3, 1] = 0.7                       # giống nghĩa, gần nhau → nối
    blocks = gr.make_blocks(arts, T, M, tfidf_th=0.15, dense_th=0.6)
    assert sorted(map(sorted, blocks)) == [[0, 1, 3], [2]]


def test_nhom_qua_lon_bi_chia_lai_bang_nguong_chat_hon():
    arts = _arts(["2026-09-14T08:00:00+07:00"] * 6)
    T = np.zeros((6, 6)); M = np.full((6, 6), 0.65)
    M[:3, :3] = M[3:, 3:] = 0.95                  # hai cụm chặt nối với nhau bằng cạnh lỏng
    blocks = gr.make_blocks(arts, T, M, tfidf_th=0.15, dense_th=0.6, cap=4)
    assert sorted(map(sorted, blocks)) == [[0, 1, 2], [3, 4, 5]]


def test_chia_phan_cho_agent_khong_cat_nhom_va_phu_du():
    blocks = [list(range(50)), list(range(50, 60)), list(range(60, 70)), [70], [71]]
    parts = gr.split_parts(blocks, n_parts=3)
    seen = [b for p in parts for b in p]
    assert sorted(seen) == list(range(len(blocks)))          # mỗi nhóm đúng một phần
    assert any(p == [0] for p in parts)                       # nhóm 50 bài không bị chia nhỏ


def _proposal(block_members, clusters, x=()):
    return {"clusters": [{"name": f"sự kiện {k}", "members": m, "confidence": "cao"} for k, m in enumerate(clusters)],
            "x": list(x)}


def test_nhan_ket_qua_hop_le():
    arts = _arts(["2026-09-14T08:00:00+07:00"] * 4)
    blocks = [[0, 1, 2], [3]]
    out = {"0": _proposal([1, 2, 3], [[1, 2]], x=[3])}       # agent dùng STT (1-based)
    prop, problems = gr.check_proposals(arts, blocks, out)
    assert problems == []
    assert prop[0]["clusters"][0]["members"] == [0, 1] and prop[0]["x"] == [2]
    assert prop[1]["clusters"][0]["members"] == [3]           # nhóm 1 bài: tự thành cụm, không cần agent


def test_nhan_ket_qua_thieu_bai_thi_tu_them_cum_le_danh_dau_tin_thap():
    arts = _arts(["2026-09-14T08:00:00+07:00"] * 3)
    prop, problems = gr.check_proposals(arts, [[0, 1, 2]], {"0": _proposal([], [[1, 2]])})
    lone = [c for c in prop[0]["clusters"] if c["members"] == [2]]
    assert lone and lone[0]["confidence"] == "thấp"
    assert any("thiếu" in p for p in problems)


def test_nhan_ket_qua_bai_ngoai_nhom_hoac_trung_thi_bao_loi():
    arts = _arts(["2026-09-14T08:00:00+07:00"] * 3)
    with pytest.raises(ValueError, match="ngoài nhóm|hai lần"):
        gr.check_proposals(arts, [[0, 1], [2]], {"0": _proposal([], [[1, 3]])})
    with pytest.raises(ValueError, match="hai lần"):
        gr.check_proposals(arts, [[0, 1], [2]], {"0": _proposal([], [[1, 2], [2]])})


def test_sinh_man_hinh_duyet_tu_chua_du_lieu(tmp_path):
    arts = _arts(["2026-09-14T08:00:00+07:00"] * 3)
    prop = [{"members": [0, 1], "clusters": [{"name": "A", "members": [0, 1], "confidence": "cao"}], "x": []},
            {"members": [2], "clusters": [{"name": "", "members": [2], "confidence": "cao"}], "x": []}]
    html = gr.build_review(arts, prop, "ds1", tmp_path)
    text = html.read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', text, re.DOTALL).group(1))
    assert data["dataset"] == "ds1" and len(data["blocks"]) == 2 and "__DATA__" not in text


def test_de_xuat_cua_claude_xuat_ra_csv_cung_dang_cong_cu_gan():
    from eventrank.evaluation.gold_clusters import clusters_from_links
    arts = _arts(["2026-09-14T08:00:00+07:00"] * 4)
    prop = [{"members": [0, 1, 2], "clusters": [{"name": "A", "members": [0, 2], "confidence": "cao"}], "x": [1]},
            {"members": [3], "clusters": [{"name": "", "members": [3], "confidence": "cao"}], "x": []}]
    rows = gr.proposal_rows(arts, prop, "ds1")
    links = {r["article_id"]: r["link_to"] for r in rows}
    assert links == {"a0": "", "a1": "x", "a2": "a0", "a3": ""}
    cl = clusters_from_links([a["id"] for a in arts], links)
    assert cl["a0"] == cl["a2"] != cl["a3"] and rows[0]["annotator"] == "claude"
