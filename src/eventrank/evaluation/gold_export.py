"""Gộp dữ liệu nhãn thành HAI file tự chứa (mở được bằng Excel, đọc được bằng pandas) thay cho các thư mục nhiều file.

    uv run python -m eventrank.evaluation.gold_export
        → data/datasets/cap_su_kien_v4.csv        cặp quan hệ (train embedding + 2 tập đo), kèm văn bản hai bài
        → data/datasets/cum_su_kien_14-15_09.csv  tập vàng gom cụm, mỗi bài một dòng, kèm tóm tắt

Nguồn: gói Kaggle `data/temp/kaggle_upload/` (v4 bản 2: v4_pairs, v4_test, v4_test_hard, v4_test_strata, articles.jsonl)
và `data/gold_clusters/v1/` (articles.jsonl, gold_clusters_v2.csv, llm/tom_tat_*.json). Thư mục gốc vẫn giữ để tái lập.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from eventrank.evaluation.gold_clusters import DEFAULT_OUT, ROOT

PAIRS_SRC = ROOT / "data/temp/kaggle_upload"
OUT_DIR = ROOT / "data/datasets"
SCORE = {"3": "1.0", "2": "0.6", "1": "0.3", "0": "0.0"}            # thang 4 mức → điểm CoSENT


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:     # BOM: Excel mở đúng tiếng Việt
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def export_pairs(src: str | Path = PAIRS_SRC, out: str | Path = OUT_DIR / "cap_su_kien_v4.csv") -> Path:
    """Một dòng một cặp: split (train / test / test_hard), mức 0–3, điểm, nguồn nhãn, trọng số tầng (test), văn bản hai bài."""
    src = Path(src)
    arts = {}
    with open(src / "articles.jsonl", encoding="utf-8") as f:
        for line in f:
            a = json.loads(line)
            arts[a["article_id"]] = a
    strata = json.loads((src / "v4_test_strata.json").read_text(encoding="utf-8"))
    test = _read(src / "v4_test.csv")
    n_bucket = Counter(r["bucket"] for r in test)
    rows = []
    for split, recs in (("train", _read(src / "v4_pairs.csv")), ("test", test), ("test_hard", _read(src / "v4_test_hard.csv"))):
        for r in recs:
            a, b = arts[r["a"]], arts[r["b"]]
            gap = abs(datetime.fromisoformat(b["published_at"]) - datetime.fromisoformat(a["published_at"]))
            bucket = r.get("bucket", "")
            rows.append({
                "split": split, "a": r["a"], "b": r["b"], "level": r["level"],
                "score": r.get("score") or SCORE[r["level"]],
                "label_source": r.get("source", "claude"),             # rule = luật nhãn yếu, claude = Claude gán mù, human = người
                "bucket": bucket,
                "weight": f"{strata[bucket] / n_bucket[bucket]:.1f}" if bucket in strata else "",   # Horvitz–Thompson cho tập test
                "gap_hours": f"{gap.total_seconds() / 3600:.1f}",
                "published_at_a": a["published_at"], "source_a": a["source"].lower(), "text_a": a["text"],
                "published_at_b": b["published_at"], "source_b": b["source"].lower(), "text_b": b["text"],
            })
    return _write(Path(out), rows)


def export_clusters(src: str | Path = DEFAULT_OUT, out: str | Path = OUT_DIR / "cum_su_kien_14-15_09.csv",
                    tune_day: str = "2026-09-14") -> Path:
    """Một dòng một bài của cửa sổ: sự kiện (event_id, tên, độ tin, cỡ), split tune/test theo ngày, văn bản, tóm tắt Claude."""
    src = Path(src)
    with open(src / "articles.jsonl", encoding="utf-8") as f:
        arts = [json.loads(line) for line in f if line.strip()]
    gold = {r["article_id"]: r for r in _read(src / "gold_clusters_v2.csv")}
    summ: dict[str, dict] = {}
    for f in sorted((src / "llm").glob("tom_tat_[0-9]*.json")):
        summ.update(json.loads(f.read_text(encoding="utf-8")))
    rows = []
    for a in sorted(arts, key=lambda a: a["stt"]):
        g, s = gold[a["id"]], summ.get(str(a["stt"]), {})
        rows.append({
            "event_id": g["cluster_id"], "event_name": g["cluster_name"], "event_confidence": g["confidence"],
            "event_size": g["cluster_size"], "split": "tune" if a["t"][:10] == tune_day else "test",
            "stt": a["stt"], "article_id": a["id"], "published_at": a["t"], "source": a["source"],
            "title": a["title"], "sapo": a.get("sapo", ""), "url": a.get("url", ""),
            "su_viec": s.get("su_viec", ""), "tom_tat": s.get("tom_tat", ""), "dang_bai": s.get("dang_bai", ""),
        })
    return _write(Path(out), rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()
    for path in (export_pairs(out=Path(args.out) / "cap_su_kien_v4.csv"),
                 export_clusters(out=Path(args.out) / "cum_su_kien_14-15_09.csv")):
        rows = _read(path)
        print(f"{path} · {len(rows):,} dòng · {path.stat().st_size / 1e6:.1f} MB · "
              + ", ".join(f"{k} {v:,}" for k, v in Counter(r["split"] for r in rows).items()))


if __name__ == "__main__":
    main()
