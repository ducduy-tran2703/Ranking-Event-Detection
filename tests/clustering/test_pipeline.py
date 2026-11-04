import csv
import json

import numpy as np
import pytest

from eventrank.clustering import pipeline as pl

CFG = {"algo_version": "vt", "model": "fake", "model_version": "fake", "prep": "raw", "algo": "agglo",
       "threshold": 0.8, "window_hours": 48}


def _silver(tmp_path, rows):
    d = tmp_path / "silver" / "s"
    d.mkdir(parents=True)
    (d / "a.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return str(tmp_path / "silver" / "*" / "*.jsonl")


def _art(aid, t, title, source="vnexpress"):
    return {"article_id": aid, "published_at": t, "source": source, "title": title, "sapo": "", "category": "X"}


def _topic_encoder(xs):
    """Vector theo từ đầu tiên của tiêu đề: cùng từ đầu → cùng hướng."""
    E = np.array([[1.0, 0.0] if x.startswith("Bão") else [0.0, 1.0] for x in xs], dtype=np.float32)
    return E


def test_load_config_kiem_tra_khoa(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("algo: agglo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="thiếu khoá"):
        pl.load_config(f)
    assert pl.load_config()["algo"] in ("agglo", "single_pass")         # file thật của repo hợp lệ


def test_load_silver_loc_ngay_bo_trung_bo_thieu_ngay(tmp_path):
    g = _silver(tmp_path, [_art("b", "2026-09-15T09:00:00+07:00", "B"), _art("a", "2026-09-15T08:00:00+07:00", " A  x "),
                           _art("a", "2026-09-15T08:00:00+07:00", "trùng"), _art("c", "", "không ngày"),
                           _art("d", "2026-09-17T08:00:00+07:00", "ngoài khoảng")])
    arts = pl.load_silver(g, "2026-09-15", "2026-09-16")
    assert [a["id"] for a in arts] == ["a", "b"] and arts[0]["title"] == "A x"


def test_event_tables_id_medoid_va_thu_tu():
    arts = [{"id": f"id{i}", "t": f"2026-09-15T0{i}:00:00+07:00", "source": s, "category": "", "title": f"t{i}"}
            for i, s in enumerate(["a", "b", "a", "c"])]
    E = np.array([[1, 0], [0.8, 0.6], [0.6, 0.8], [0, 1]], dtype=np.float32)
    rows, events = pl.event_tables(arts, E, np.array([0, 0, 0, 1]))
    e = events[0]
    assert e["event_id"] == "E20260915-id0" and e["size"] == 3 and e["n_sources"] == 2
    assert e["medoid_article_id"] == "id1"                             # bài giữa giống hai bài kia nhất
    assert [r["is_medoid"] for r in rows] == [0, 1, 0, 1]
    assert [r["event_id"] for r in rows][-1] == "E20260915-id3"


def test_run_ghi_bang_su_kien(tmp_path):
    g = _silver(tmp_path, [_art("1", "2026-09-15T08:00:00+07:00", "Bão số 5 vào bờ"),
                           _art("2", "2026-09-15T09:00:00+07:00", "Bão số 5 gây mưa", "tuoitre"),
                           _art("3", "2026-09-15T10:00:00+07:00", "Giá vàng giảm"),
                           _art("4", "2026-09-20T08:00:00+07:00", "Bão số 6 hình thành")])   # > 48h: sự kiện khác
    out = pl.run(CFG, g, tmp_path / "out", encoder=_topic_encoder, log=lambda s: None)
    with open(out / "su_kien.csv", encoding="utf-8") as f:
        ev = list(csv.DictReader(f))
    assert [int(e["size"]) for e in ev] == [2, 1, 1] and ev[0]["sources"] == "tuoitre:1 vnexpress:1"
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["n_articles"] == 4 and m["n_events"] == 3 and m["n_events_multi"] == 1
    assert (tmp_path / "out" / "cache" / "emb_fake.npz").exists()
