"""Trang trực quan bảng sự kiện (đầu ra của pipeline gom cụm): một file HTML tự chứa, mở bằng trình duyệt.

    uv run python -m eventrank.evaluation.events_viz           # hoặc: make events-viz
        → data/events/<algo_version>/truc_quan.html (chứa tiêu đề bài báo — chỉ dùng trong nhóm)

Đọc `bai_su_kien.csv`, `su_kien.csv`, `manifest.json` do `eventrank.clustering.pipeline` sinh ra; chuyên mục chuẩn hoá lấy
từ Gold NER (`data/lake/gold/gold_data.jsonl`, nếu có); điểm B-Cubed so với tập vàng tính lại nếu có
`data/gold_clusters/v1/`. Mọi con số trong phần nhận xét của trang được tính từ dữ liệu → chạy lại pipeline thì sinh lại trang.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from eventrank.clustering.pipeline import OUT, ROOT

TEMPLATE = Path(__file__).with_name("events_viz.html")
GOLD_NER = ROOT / "data/lake/gold/gold_data.jsonl"
GOLD_DIR = ROOT / "data/gold_clusters/v1"
TIMELINE_FROM = "2026-07-01"                                          # trước đó Silver rất thưa
SIZE_BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 9), (10, 19), (20, 49), (50, 10**9)]
SOURCES = ["tuoitre", "thanhnien", "vietnamnet", "vnexpress", "nhandan", "baochinhphu"]   # thứ tự màu cố định


def _hours(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600


def _categories(ids: set[str], path: Path | None = None) -> dict[str, str]:
    path = path or GOLD_NER
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["article_id"] in ids:
                out[r["article_id"]] = r.get("standardized_category") or ""
    return out


def _gold_scores(pred: dict[str, str], gold_dir: Path | None = None) -> list[dict]:
    """B-Cubed theo từng ngày của tập vàng; bỏ ngày không có bài chung (bảng sự kiện gom khoảng ngày khác)."""
    f = (gold_dir or GOLD_DIR) / "gold_clusters_v2.csv"
    if not f.exists():
        return []
    from eventrank.evaluation.bcubed import bcubed

    with open(f, encoding="utf-8-sig") as fh:
        gold = {r["article_id"]: (r["cluster_id"], r["published_at"][:10]) for r in csv.DictReader(fh)}
    out = []
    for day in sorted({d for _, d in gold.values()}):
        ids = [i for i, (c, d) in gold.items() if d == day and c != "x" and i in pred]
        if not ids:
            continue
        p, r, f1 = bcubed({i: pred[i] for i in ids}, {i: gold[i][0] for i in ids})
        out.append({"day": day, "n": len(ids), "precision": p, "recall": r, "f1": f1})
    return out


def build_data(events_dir: str | Path) -> dict:
    events_dir = Path(events_dir)
    with open(events_dir / "bai_su_kien.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(events_dir / "su_kien.csv", encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    manifest = json.loads((events_dir / "manifest.json").read_text(encoding="utf-8"))
    by = defaultdict(list)
    for r in rows:
        by[r["event_id"]].append(r)
    cat = _categories({r["article_id"] for r in rows})
    sources = [s for s in SOURCES if any(r["source"] == s for r in rows)] + \
        sorted({r["source"] for r in rows} - set(SOURCES))
    sidx = {s: k for k, s in enumerate(sources)}

    size_of = {e["event_id"]: int(e["size"]) for e in events}
    buckets = [{"label": f"{a}" if a == b else (f"{a}–{b}" if b < 10**9 else f"≥ {a}"),
                "events": sum(a <= s <= b for s in size_of.values()),
                "articles": sum(s for s in size_of.values() if a <= s <= b)} for a, b in SIZE_BUCKETS]

    days = sorted({r["published_at"][:10] for r in rows if r["published_at"][:10] >= TIMELINE_FROM})
    per_day = {d: [0] * len(sources) for d in days}
    multi_art_day = Counter()
    for r in rows:
        d = r["published_at"][:10]
        if d in per_day:
            per_day[d][sidx[r["source"]]] += 1
            if size_of[r["event_id"]] >= 2:
                multi_art_day[d] += 1
    new_multi = Counter(e["first_seen"][:10] for e in events if int(e["size"]) >= 2)

    multi, co = [], [[0] * len(sources) for _ in sources]
    first, part, lags, spans = Counter(), Counter(), [], []
    cat_n, cat_multi_art = Counter(), Counter()
    for r in rows:
        c = cat.get(r["article_id"], "")
        cat_n[c] += 1
        if size_of[r["event_id"]] >= 2:
            cat_multi_art[c] += 1
    cat_events = defaultdict(list)
    for e in events:
        if int(e["size"]) < 2:
            continue
        rs = sorted(by[e["event_id"]], key=lambda r: (r["published_at"], r["article_id"]))
        ss = sorted({sidx[r["source"]] for r in rs})
        for a in ss:
            for b in ss:
                co[a][b] += 1
        span = _hours(rs[0]["published_at"], rs[-1]["published_at"])
        spans.append(span)
        if len(ss) >= 2:
            first[sidx[rs[0]["source"]]] += 1
            for s in ss:
                part[s] += 1
            second = next(r for r in rs if r["source"] != rs[0]["source"])
            lags.append(_hours(rs[0]["published_at"], second["published_at"]))
        main_cat = Counter(cat.get(r["article_id"], "") for r in rs).most_common(1)[0][0]
        cat_events[main_cat].append(len(rs))
        multi.append([e["event_id"], e["first_seen"][:16], len(rs), len(ss), round(span, 1), e["medoid_title"], main_cat,
                      [[r["published_at"][5:16].replace("T", " "), sidx[r["source"]], r["title"], int(r["is_medoid"])]
                       for r in rs]])
    multi.sort(key=lambda m: m[1])
    pred = {r["article_id"]: r["event_id"] for r in rows}
    return {
        "manifest": manifest, "sources": sources, "n_articles": len(rows), "n_events": len(events),
        "buckets": buckets,
        "days": days, "per_day": [per_day[d] for d in days], "multi_art_day": [multi_art_day[d] for d in days],
        "new_multi_day": [new_multi[d] for d in days],
        "n_sources_hist": [sum(m[3] == k for m in multi) for k in range(1, len(sources) + 1)],
        "spans": sorted(round(s, 2) for s in spans), "lags": sorted(round(x, 2) for x in lags),
        "co": co, "first": [first[k] for k in range(len(sources))], "part": [part[k] for k in range(len(sources))],
        "src_articles": [sum(r["source"] == s for r in rows) for s in sources],
        "src_multi_articles": [sum(r["source"] == s and size_of[r["event_id"]] >= 2 for r in rows) for s in sources],
        "categories": sorted(({"name": c or "(không rõ)", "articles": cat_n[c], "multi_articles": cat_multi_art[c],
                               "multi_events": len(cat_events[c]),
                               "avg_size": sum(cat_events[c]) / len(cat_events[c]) if cat_events[c] else 0}
                              for c in cat_n), key=lambda x: -x["multi_articles"] / max(1, x["articles"])),
        "multi": multi, "gold": _gold_scores(pred),
    }


def build(events_dir: str | Path, out: str | Path | None = None) -> Path:
    data = build_data(events_dir)
    out = Path(out) if out else Path(events_dir) / "truc_quan.html"
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--events", default=str(OUT / "v1"), help="thư mục đầu ra của pipeline (data/events/<algo_version>)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    p = build(a.events, a.out)
    print(f"→ {p} ({p.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
