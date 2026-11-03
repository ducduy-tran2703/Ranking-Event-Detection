import csv
import json

from eventrank.evaluation import events_viz as ev


def _write(tmp_path):
    arts = [("E1", "a1", "2026-09-15T08:00:00+07:00", "tuoitre", 1), ("E1", "a2", "2026-09-15T10:00:00+07:00", "vnexpress", 0),
            ("E1", "a3", "2026-09-15T12:00:00+07:00", "tuoitre", 0), ("E2", "b1", "2026-09-15T09:00:00+07:00", "nhandan", 1)]
    with open(tmp_path / "bai_su_kien.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "article_id", "published_at", "source", "category", "title", "is_medoid"])
        for e, a, t, s, m in arts:
            w.writerow([e, a, t, s, "X", f"tiêu đề {a}", m])
    with open(tmp_path / "su_kien.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "size", "n_sources", "sources", "first_seen", "last_seen", "medoid_article_id", "medoid_title"])
        w.writerow(["E1", 3, 2, "tuoitre:2 vnexpress:1", arts[0][2], arts[2][2], "a1", "tiêu đề a1"])
        w.writerow(["E2", 1, 1, "nhandan:1", arts[3][2], arts[3][2], "b1", "tiêu đề b1"])
    (tmp_path / "manifest.json").write_text(json.dumps({"config": {}}), encoding="utf-8")


def test_build_data_tong_hop_dung(tmp_path, monkeypatch):
    _write(tmp_path)
    monkeypatch.setattr(ev, "GOLD_NER", tmp_path / "khong_co.jsonl")
    monkeypatch.setattr(ev, "GOLD_DIR", tmp_path / "khong_co")
    d = ev.build_data(tmp_path)
    assert d["n_articles"] == 4 and d["n_events"] == 2
    assert d["buckets"][0] == {"label": "1", "events": 1, "articles": 1}
    assert d["buckets"][2]["events"] == 1 and d["buckets"][2]["articles"] == 3
    assert d["n_sources_hist"][:2] == [0, 1] and d["spans"] == [4.0] and d["lags"] == [2.0]
    tt, vn = d["sources"].index("tuoitre"), d["sources"].index("vnexpress")
    assert d["first"][tt] == 1 and d["part"][vn] == 1 and d["co"][tt][vn] == 1
    m = d["multi"][0]
    assert m[0] == "E1" and m[2] == 3 and [a[3] for a in m[7]] == [1, 0, 0]
    assert d["gold"] == []


def test_build_nhung_du_lieu_vao_html(tmp_path, monkeypatch):
    _write(tmp_path)
    monkeypatch.setattr(ev, "GOLD_NER", tmp_path / "khong_co.jsonl")
    monkeypatch.setattr(ev, "GOLD_DIR", tmp_path / "khong_co")
    html = ev.build(tmp_path).read_text(encoding="utf-8")
    assert "/*__DATA__*/null" not in html and '"n_events":2' in html
