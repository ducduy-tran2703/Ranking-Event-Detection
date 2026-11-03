import csv
import json

from eventrank.evaluation import gold_export as ge


def _rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _w(path, head, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def test_xuat_cap_gop_train_test_kem_van_ban_va_trong_so(tmp_path):
    arts = [{"article_id": f"a{i}", "source": "tuoitre", "category": "", "published_at": f"2026-09-0{i + 1}T08:00:00+07:00",
             "text": f"Tiêu đề {i}. Sapo {i}"} for i in range(4)]
    (tmp_path / "articles.jsonl").write_text("\n".join(json.dumps(a, ensure_ascii=False) for a in arts), encoding="utf-8")
    _w(tmp_path / "v4_pairs.csv", ["a", "b", "level", "score", "source"], [["a0", "a1", "3", "1.0", "rule"]])
    _w(tmp_path / "v4_test.csv", ["a", "b", "bucket", "level", "source"],
       [["a1", "a2", "r3", "3", "human"], ["a2", "a3", "r3", "0", "claude"]])
    _w(tmp_path / "v4_test_hard.csv", ["a", "b", "level"], [["a0", "a3", "2"]])
    (tmp_path / "v4_test_strata.json").write_text(json.dumps({"r3": 10}), encoding="utf-8")
    out = ge.export_pairs(tmp_path, tmp_path / "cap.csv")
    rows = _rows(out)
    assert [r["split"] for r in rows] == ["train", "test", "test", "test_hard"]
    assert rows[0]["text_a"] == "Tiêu đề 0. Sapo 0" and rows[0]["gap_hours"] == "24.0"
    assert rows[1]["label_source"] == "human" and rows[1]["weight"] == "5.0"      # 10 cặp tầng r3 / 2 cặp mẫu
    assert rows[3]["score"] == "0.6" and rows[3]["weight"] == ""                  # mức 2 → 0,6; tập khác chữ không trọng số


def test_xuat_cum_moi_bai_mot_dong_kem_tom_tat(tmp_path):
    arts = [{"stt": 1, "id": "a0", "t": "2026-09-14T08:00:00+07:00", "source": "tuoitre", "title": "A", "sapo": "sa",
             "url": "u0"},
            {"stt": 2, "id": "a1", "t": "2026-09-15T08:00:00+07:00", "source": "vnexpress", "title": "B", "sapo": "",
             "url": "u1"}]
    (tmp_path / "articles.jsonl").write_text("\n".join(json.dumps(a, ensure_ascii=False) for a in arts), encoding="utf-8")
    _w(tmp_path / "gold_clusters_v2.csv", ["cluster_id", "cluster_name", "confidence", "cluster_size", "article_id"],
       [["E0001", "Sự kiện A", "cao", "1", "a0"], ["x", "(loại)", "", "0", "a1"]])
    (tmp_path / "llm").mkdir()
    (tmp_path / "llm" / "tom_tat_1.json").write_text(json.dumps({"1": {"su_viec": "sv", "tom_tat": "tt", "dang_bai": "d"}}),
                                                     encoding="utf-8")
    out = ge.export_clusters(tmp_path, tmp_path / "cum.csv", tune_day="2026-09-14")
    rows = _rows(out)
    assert [(r["event_id"], r["split"]) for r in rows] == [("E0001", "tune"), ("x", "test")]
    assert rows[0]["su_viec"] == "sv" and rows[1]["su_viec"] == ""
