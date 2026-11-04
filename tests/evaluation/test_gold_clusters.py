import csv
import json
import re
import unicodedata

import pytest

from eventrank.evaluation import gold_clusters as gc


def _art(aid, t, title, sapo="", source="tuoitre"):
    return {"article_id": aid, "source": source, "category": "Thể Thao", "title": title, "sapo": sapo,
            "url": f"https://x/{aid}", "published_at": t}


@pytest.fixture
def silver(tmp_path):
    """Silver mẫu: có bài ngoài cửa sổ, thứ tự lộn xộn, tiêu đề NFD, thiếu sapo, trùng article_id."""
    rows_a = [
        {**_art("a3", "2026-09-14T09:00:00+07:00", "U23 Việt Nam thắng Kuwait 2-1", "Trận ra quân tại Asiad"),
         "content_text": "Đoạn một  có   khoảng trắng.\n\nĐoạn hai. " + "Câu dài. " * 400},
        _art("a1", "2026-09-14T06:00:00+07:00", unicodedata.normalize("NFD", "Nhận định U23 Việt Nam gặp Kuwait"),
             "Trận đấu tối nay"),
        _art("old", "2026-09-13T23:59:00+07:00", "Bài hôm trước", "ngoài cửa sổ"),
    ]
    rows_b = [
        _art("a2", "2026-09-14T07:00:00+07:00", "Giá vàng hôm nay 14/9 tăng mạnh", None, source="vnexpress"),
        _art("a4", "2026-09-15T08:00:00+07:00", "U23 Việt Nam thắng Kuwait, HLV nói gì", "Sau trận thắng Kuwait",
             source="vnexpress"),
        _art("a1", "2026-09-14T06:00:00+07:00", "Nhận định U23 Việt Nam gặp Kuwait", "Trận đấu tối nay"),
        _art("late", "2026-09-16T00:00:00+07:00", "Bài hôm sau", "ngoài cửa sổ"),
    ]
    for name, rows in (("tuoitre", rows_a), ("vnexpress", rows_b)):
        d = tmp_path / "silver" / name
        d.mkdir(parents=True)
        (d / "x.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return str(tmp_path / "silver" / "*" / "*.jsonl")


def test_load_window_loc_cua_so_sap_xep_chuan_hoa_bo_trung(silver):
    arts = gc.load_window(silver, "2026-09-14", "2026-09-16")
    assert [a["id"] for a in arts] == ["a1", "a2", "a3", "a4"]                 # theo thời gian, bỏ trùng a1
    assert arts[0]["title"] == unicodedata.normalize("NFC", arts[0]["title"])
    assert arts[1]["sapo"] == ""                                                # sapo None → chuỗi rỗng


def test_goi_y_chi_lay_bai_truoc_trong_48h_giong_nhat_dau_tien(silver):
    arts = gc.load_window(silver, "2026-09-14", "2026-09-16")
    sug = gc.suggest(arts, k=5, window_hours=48)
    assert sug[0] == []                                                         # bài đầu: không có bài trước
    assert all(j < i for i, s in enumerate(sug) for j, _ in s)
    assert sug[3][0][0] == 2                                                    # "thắng Kuwait" ↔ "thắng Kuwait"
    sims = [s for _, s in sug[3]]
    assert sims == sorted(sims, reverse=True)
    far = gc.suggest(arts, k=5, window_hours=12)
    assert all(j != 0 for j, _ in far[3])                                       # a1 cách a4 26h > 12h


def test_cum_tu_lien_ket_noi_chuoi_va_bai_loai():
    order = ["a", "b", "c", "d", "e"]
    links = {"a": "", "b": "a", "c": "b", "d": "", "e": "x"}                   # x: bài tổng hợp → loại
    cl = gc.clusters_from_links(order, links)
    assert cl["a"] == cl["b"] == cl["c"]
    assert cl["d"] != cl["a"]
    assert "e" not in cl


def test_lien_ket_toi_bai_ngoai_doan_van_gop_duoc():
    # hai bài cùng trỏ tới một bài người khác gán (không nằm trong order) → cùng cụm
    cl = gc.clusters_from_links(["b", "c"], {"b": "z", "c": "z"})
    assert cl["b"] == cl["c"]


def _write_labels(path, annotator, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset", "annotator", "stt", "article_id", "link_to", "unsure", "labeled_at"])
        for stt, (aid, link) in enumerate(rows, 1):
            w.writerow(["ds", annotator, stt, aid, link, 0, "2026-10-19T10:00:00"])


def test_build_sinh_html_tu_chua_du_lieu(silver, tmp_path):
    out = tmp_path / "gold"
    html = gc.build(silver, "2026-09-14", "2026-09-16", out)
    text = html.read_text(encoding="utf-8")
    assert "__DATA__" not in text
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', text, re.DOTALL).group(1))
    assert [a["id"] for a in data["articles"]] == ["a1", "a2", "a3", "a4"]
    assert len(data["suggest"]) == 4 and data["dataset"]
    assert (out / "articles.jsonl").exists()


def test_merge_noi_hai_nguoi_qua_lien_ket_cat_doan(silver, tmp_path):
    out = tmp_path / "gold"
    gc.build(silver, "2026-09-14", "2026-09-16", out)
    _write_labels(tmp_path / "A.csv", "A", [("a1", ""), ("a2", "")])
    _write_labels(tmp_path / "B.csv", "B", [("a3", "a1"), ("a4", "a3")])     # B nối sang cụm của A
    res = gc.merge(out, [tmp_path / "A.csv", tmp_path / "B.csv"])
    with open(res, encoding="utf-8") as f:
        cl = {r["article_id"]: r["cluster_id"] for r in csv.DictReader(f)}
    assert cl["a1"] == cl["a3"] == cl["a4"] != cl["a2"]


def test_merge_bao_loi_khi_mot_bai_bi_gan_hai_lan(silver, tmp_path):
    out = tmp_path / "gold"
    gc.build(silver, "2026-09-14", "2026-09-16", out)
    _write_labels(tmp_path / "A.csv", "A", [("a1", "")])
    _write_labels(tmp_path / "B.csv", "B", [("a1", "")])
    with pytest.raises(ValueError, match="a1"):
        gc.merge(out, [tmp_path / "A.csv", tmp_path / "B.csv"])


def test_agree_do_dong_thuan_va_liet_ke_bai_lech(silver, tmp_path):
    out = tmp_path / "gold"
    gc.build(silver, "2026-09-14", "2026-09-16", out)
    _write_labels(tmp_path / "A.csv", "A", [("a1", ""), ("a2", ""), ("a3", "a1"), ("a4", "a3")])
    _write_labels(tmp_path / "B.csv", "B", [("a1", ""), ("a2", ""), ("a3", "a1"), ("a4", "")])
    same = gc.agree(out, tmp_path / "A.csv", tmp_path / "A.csv")
    assert same["f1"] == pytest.approx(1.0) and same["disagreements"] == []
    diff = gc.agree(out, tmp_path / "A.csv", tmp_path / "B.csv")
    assert diff["f1"] < 1.0
    assert "a4" in {d["article_id"] for d in diff["disagreements"]}


def test_duong_dan_mac_dinh_khong_phu_thuoc_thu_muc_dang_dung(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                                  # chạy lệnh từ thư mục khác
    assert gc.DEFAULT_OUT.is_absolute() and gc.DEFAULT_OUT.parts[-3:] == ("data", "gold_clusters", "v1")


def test_chua_sinh_cong_cu_thi_bao_loi_de_hieu(tmp_path):
    with pytest.raises(FileNotFoundError, match="make gold-tool"):
        gc.agree(tmp_path / "chua_co", tmp_path / "A.csv", tmp_path / "B.csv")


def test_thieu_file_nhan_thi_bao_loi_de_hieu(silver, tmp_path):
    out = tmp_path / "gold"
    gc.build(silver, "2026-09-14", "2026-09-16", out)
    with pytest.raises(FileNotFoundError, match="Xuất CSV"):
        gc.agree(out, tmp_path / "A.csv", tmp_path / "B.csv")


def test_load_window_kem_doan_dau_noi_dung_da_cat_gon(silver):
    arts = {a["id"]: a for a in gc.load_window(silver, "2026-09-14", "2026-09-16")}
    body = arts["a3"]["body"]
    assert body.startswith("Đoạn một có khoảng trắng.\nĐoạn hai.")             # gộp khoảng trắng, giữ xuống đoạn
    assert len(body) <= gc.BODY_CHARS + 1 and body.endswith("…")               # cắt ở cuối câu, có dấu …
    assert arts["a1"]["body"] == ""                                             # bài không có nội dung


def test_goi_y_kem_tu_chung_giai_thich_do_giong(silver):
    arts = gc.load_window(silver, "2026-09-14", "2026-09-16")
    sug = gc.suggest(arts, k=5, terms=4)
    j, sim, terms = sug[3][0]                       # a4 "U23 Việt Nam thắng Kuwait, HLV nói gì" ↔ a3
    assert j == 2 and 0 < sim <= 1
    assert any("kuwait" in t for t in terms) and len(terms) <= 4
    assert not any(a in b for a in terms for b in terms if a != b)   # không lặp "kuwait" và "thắng kuwait"


def test_tu_chung_bo_tu_qua_pho_bien():
    base = {"source": "tuoitre", "category": "", "url": "", "t": "2026-09-14T08:00:00+07:00", "sapo": ""}
    arts = [{**base, "id": f"p{i}", "title": f"tin của với số {i}"} for i in range(40)]          # "của", "với" ở mọi bài
    arts += [{**base, "id": "q1", "title": "Bộ trưởng kêu gọi của với"}, {**base, "id": "q2", "title": "Trump kêu gọi của với"}]
    j, _, terms = gc.suggest(arts, k=3, terms=5)[-1][0]
    assert j == 40 and terms == ["kêu gọi"]


def test_build_gan_tom_tat_cua_claude_theo_stt(silver, tmp_path):
    out = tmp_path / "gold"
    (out / "llm").mkdir(parents=True)
    (out / "llm" / "tom_tat_1.json").write_text(json.dumps(
        {"3": {"su_viec": "U23 VN thắng Kuwait", "tom_tat": "Trận ra quân.", "dang_bai": "tin sự kiện"}},
        ensure_ascii=False), encoding="utf-8")
    html = gc.build(silver, "2026-09-14", "2026-09-16", out)
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>',
                                html.read_text(encoding="utf-8"), re.DOTALL).group(1))
    by_id = {a["id"]: a for a in data["articles"]}
    assert by_id["a3"]["summary"]["su_viec"] == "U23 VN thắng Kuwait"           # STT 3 = a3 (theo thời gian)
    assert "summary" not in by_id["a1"]
    assert "summary" not in json.loads((out / "articles.jsonl").read_text(encoding="utf-8").splitlines()[2])
