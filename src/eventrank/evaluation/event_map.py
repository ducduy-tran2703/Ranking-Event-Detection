"""Bản đồ 2D các bài của MỘT ngày (trang web "Trực quan gom cụm", `/api/events/map`).

    uv run --group embed python -m eventrank.evaluation.event_map --date 2026-09-10
        → data/runs/<run_id>/ban_do/2026-09-10.json   (run = EVENTS_RUN_DIR hoặc run đầy đủ mới nhất, như API)

Cách tính giống `data/temp/thiet_ke_web/viz.json` (bản thiết kế đã duyệt): vector đệm của mô hình embedding mà run dùng
(`data/events/cache/emb_<model_version>.npz`, cùng đệm với `make cluster`), lấy các bài trong `bai_su_kien.csv` của run có
`published_at` trong ngày (giờ VN), t-SNE 2 chiều (perplexity 25, metric cosine, init pca, random_state 0), chuẩn hoá về
[0, 100]. Tô màu `--top` (mặc định 8) sự kiện có nhiều bài nhất TRONG ngày.

File ra KHÔNG chứa tên sự kiện — chỉ event_id + số bài; API ghép tên ĐANG HIỂN THỊ (đã áp luật ẩn tên) lúc phục vụ.
Ngày giao cửa sổ ẩn tên (`EVENTS_HIDE_NAMES_WINDOW`, mặc định 14–15/09/2026) bị từ chối ở cả script lẫn API.
Chỉ đọc file ở máy, chỉ ghi vào thư mục run; không đọc/ghi R2.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

# Công cụ dòng lệnh (lá): dùng lại đúng luật chọn run + cửa sổ ẩn tên của tầng phục vụ, không chép lại.
from eventrank.serving.store import (
    MAP_DIR,
    ROOT,
    RunNotFound,
    day_overlaps,
    find_run_dir,
    parse_hide_window,
)
from eventrank.trending import score as trending

CACHE_DIR = ROOT / "data/events/cache"
TSNE = {"perplexity": 25, "metric": "cosine", "init": "pca", "random_state": 0}


def resolve_run_dir(run_dir: str | None) -> Path:
    raw = run_dir or os.environ.get("EVENTS_RUN_DIR", "").strip()
    if raw:
        p = Path(raw) if Path(raw).is_absolute() else ROOT / raw
        if not p.is_dir():
            raise RunNotFound(f"Không có thư mục run: {raw}")
        return p
    found = find_run_dir()
    if found is None:
        raise RunNotFound("Chưa có run đầy đủ trong data/runs/ (chạy `make pipeline`).")
    return found


def day_articles(run_dir: Path, date: str) -> list[dict[str, str]]:
    """Bài của run đăng trong ngày `date` (giờ VN), sắp theo (giờ đăng, article_id) để kết quả ổn định."""
    lo = trending.day(date).timestamp()
    hi = lo + 86400
    with open(run_dir / "bai_su_kien.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if lo <= datetime.fromisoformat(r["published_at"]).timestamp() < hi]
    rows.sort(key=lambda r: (datetime.fromisoformat(r["published_at"]).timestamp(), r["article_id"]))
    return rows


def project(E: np.ndarray, seed: int = 0) -> np.ndarray:
    """t-SNE 2D → toạ độ trong [0, 100] (1 chữ số thập phân). Ít bài quá thì giảm perplexity cho hợp lệ."""
    from sklearn.manifold import TSNE as _TSNE

    n = len(E)
    if n == 1:
        return np.array([[50.0, 50.0]])
    perplexity = min(TSNE["perplexity"], max(1.0, (n - 1) / 3))
    xy = _TSNE(n_components=2, perplexity=perplexity, metric=TSNE["metric"], init=TSNE["init"],
               random_state=seed).fit_transform(E.astype(np.float32))
    span = np.where(xy.max(0) - xy.min(0) > 0, xy.max(0) - xy.min(0), 1.0)
    return np.round((xy - xy.min(0)) / span * 100, 1)


def build_map(run_dir: Path, date: str, emb_path: Path | None = None, top: int = 8) -> dict:
    """Dựng dict bản đồ (chưa ghi). Ngày trong cửa sổ ẩn tên → ValueError."""
    window = parse_hide_window(os.environ.get("EVENTS_HIDE_NAMES_WINDOW"))
    if day_overlaps(date, window):
        raise ValueError(f"Ngày {date} thuộc cửa sổ ẩn tên của tập test đặt tên — không dựng bản đồ.")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    model_version = (manifest.get("versions") or {}).get("model_version", "")
    emb_path = emb_path or CACHE_DIR / f"emb_{model_version}.npz"
    if not emb_path.is_file():
        raise FileNotFoundError(f"Không có vector đệm {emb_path} (chạy `make cluster` hoặc `make pipeline` trước).")
    rows = day_articles(run_dir, date)
    if not rows:
        raise ValueError(f"Run {run_dir.name} không có bài nào ngày {date}.")
    z = np.load(emb_path, allow_pickle=False)
    pos = {a: i for i, a in enumerate(z["ids"].tolist())}
    missing = [r["article_id"] for r in rows if r["article_id"] not in pos]
    if missing:
        raise ValueError(f"{len(missing)} bài của ngày {date} không có trong {emb_path.name} (đệm của mô hình khác?)")
    E = z["E"][[pos[r["article_id"]] for r in rows]]
    xy = project(E)
    per_event = Counter(r["event_id"] for r in rows)
    ranked = sorted(per_event.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    k_of = {eid: k for k, (eid, _) in enumerate(ranked)}
    return {
        "date": date, "run_id": manifest.get("run_id") or run_dir.name, "model_version": model_version,
        "tsne": dict(TSNE), "n_bai": len(rows), "n_su_kien": len(per_event),
        "n_su_kien_nhieu_bai": sum(n >= 2 for n in per_event.values()),
        "top": [{"event_id": eid, "n": n} for eid, n in ranked],
        "diem": [[float(x), float(y), k_of.get(r["event_id"], -1)] for (x, y), r in zip(xy, rows, strict=True)],
        "tao_luc": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", action="append", required=True, help="YYYY-MM-DD (giờ VN); lặp lại để làm nhiều ngày")
    ap.add_argument("--run-dir", help="thư mục run (mặc định: EVENTS_RUN_DIR hoặc run đầy đủ mới nhất)")
    ap.add_argument("--emb", help="file .npz vector đệm (mặc định: data/events/cache/emb_<model_version>.npz)")
    ap.add_argument("--top", type=int, default=8, help="số sự kiện được tô màu")
    args = ap.parse_args(argv)
    run_dir = resolve_run_dir(args.run_dir)
    out_dir = run_dir / MAP_DIR
    code = 0
    for date in args.date:
        t0 = time.perf_counter()
        try:
            m = build_map(run_dir, date, Path(args.emb) if args.emb else None, args.top)
        except (ValueError, FileNotFoundError) as exc:
            print(f"✗ {date}: {exc}", file=sys.stderr)
            code = 1
            continue
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"{date}.json"
        path.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"→ {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {m['n_bai']} bài, "
              f"{m['n_su_kien']} sự kiện ({m['n_su_kien_nhieu_bai']} có ≥ 2 bài trong ngày), "
              f"{time.perf_counter() - t0:.1f}s")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
