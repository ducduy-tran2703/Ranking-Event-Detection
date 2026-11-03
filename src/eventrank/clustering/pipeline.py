"""Pipeline gom cụm sự kiện trên cả kho Silver: Silver → vector → cụm → bảng sự kiện.

    uv run --group embed --with pyvi python -m eventrank.clustering.pipeline
        → data/events/<algo_version>/{bai_su_kien.csv, su_kien.csv, manifest.json}

Cấu hình (mô hình, thuật toán, ngưỡng, cửa sổ, phiên bản) ở configs/clustering.yaml. Vector lưu đệm ở
data/events/cache/emb_<model_version>.npz — chạy lại chỉ encode bài mới (lần đầu ~30–40 phút CPU cho ~29 nghìn bài).

Đầu ra (ghi ở máy; KHÔNG tự ghi lên R2):
- `bai_su_kien.csv`: mỗi bài một dòng — event_id, article_id, published_at, source, category, title, is_medoid.
- `su_kien.csv`: mỗi sự kiện một dòng — event_id, size, n_sources, sources, first_seen, last_seen, medoid_article_id,
  medoid_title. Medoid = bài có cosine trung bình với các bài khác trong cụm cao nhất (hoà → bài đăng sớm hơn); dùng cho
  baseline đặt tên.
- `manifest.json`: cấu hình, số bài, số cụm, thời gian chạy.

event_id = "E" + ngày của bài sớm nhất (YYYYMMDD) + "-" + 8 ký tự đầu article_id của bài đó: xác định được từ dữ liệu, chạy
lại cùng dữ liệu + cấu hình ra cùng id. Chưa có đối chiếu ID giữa các lần chạy có dữ liệu mới (mục 9.1 — việc sau).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from eventrank.clustering.algorithms import agglo_components, single_pass
from eventrank.embeddings.encode import encode, head_text

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs/clustering.yaml"
SILVER = str(ROOT / "data/lake/silver/*/*.jsonl")
OUT = ROOT / "data/events"
_SPACE = re.compile(r"\s+")


def load_config(path: str | Path = CONFIG) -> dict:
    import yaml

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    missing = {"algo_version", "model", "model_version", "prep", "algo", "threshold", "window_hours"} - set(cfg)
    if missing:
        raise ValueError(f"thiếu khoá cấu hình: {sorted(missing)}")
    if cfg["algo"] not in ("agglo", "single_pass"):
        raise ValueError(f"algo phải là agglo hoặc single_pass, không phải {cfg['algo']!r}")
    return cfg


def _clean(s: str | None) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFC", s or "")).strip()


def load_silver(silver_glob: str = SILVER, start: str = "", end: str = "9999") -> list[dict]:
    """Bài có published_at trong [start, end) (so theo chuỗi ngày), sắp theo thời gian, bỏ trùng id. Bài không có
    published_at bị bỏ (không đặt được vào dòng thời gian)."""
    seen: dict[str, dict] = {}
    for path in sorted(glob.glob(silver_glob)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                a = json.loads(line)
                t = a.get("published_at") or ""
                if not t or not (start <= t[:10] < end) or a["article_id"] in seen:
                    continue
                seen[a["article_id"]] = {
                    "id": a["article_id"], "t": t, "source": (a.get("source") or "").lower(),
                    "category": _clean(a.get("category")), "title": _clean(a.get("title")),
                    "sapo": _clean(a.get("sapo"))}
    if not seen:
        raise FileNotFoundError(f"không có bài nào ở {silver_glob} trong [{start}, {end})")
    return sorted(seen.values(), key=lambda a: (datetime.fromisoformat(a["t"]), a["id"]))


def cluster(E: np.ndarray, times: np.ndarray, cfg: dict) -> tuple[np.ndarray, dict]:
    """Nhãn cụm cho từng bài theo cấu hình. single_pass cần ma trận N × N → chỉ dùng cho tập nhỏ."""
    if cfg["algo"] == "agglo":
        return agglo_components(E, times, cfg["threshold"], cfg["window_hours"])
    return single_pass(E @ E.T, times, cfg["threshold"], cfg["window_hours"]), {}


def event_tables(arts: list[dict], E: np.ndarray, labels: np.ndarray) -> tuple[list[dict], list[dict]]:
    """(dòng theo bài, dòng theo sự kiện), sự kiện sắp theo thời điểm xuất hiện đầu tiên."""
    members: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        members.setdefault(int(lab), []).append(i)
    events, by_article = [], {}
    for idx in members.values():
        idx.sort(key=lambda i: (arts[i]["t"], arts[i]["id"]))
        first = arts[idx[0]]
        eid = f"E{first['t'][:10].replace('-', '')}-{first['id'][:8]}"
        if len(idx) > 1:
            X = E[idx]
            avg = ((X @ X.T).sum(1) - 1) / (len(idx) - 1)
            medoid = idx[int(np.argmax(avg))]                         # argmax lấy chỉ số đầu → hoà thì bài sớm hơn
        else:
            medoid = idx[0]
        sources = Counter(arts[i]["source"] for i in idx)
        events.append({"event_id": eid, "size": len(idx), "n_sources": len(sources),
                       "sources": " ".join(f"{s}:{n}" for s, n in sorted(sources.items())),
                       "first_seen": first["t"], "last_seen": arts[idx[-1]]["t"],
                       "medoid_article_id": arts[medoid]["id"], "medoid_title": arts[medoid]["title"]})
        for i in idx:
            by_article[i] = {"event_id": eid, "article_id": arts[i]["id"], "published_at": arts[i]["t"],
                             "source": arts[i]["source"], "category": arts[i]["category"], "title": arts[i]["title"],
                             "is_medoid": int(i == medoid)}
    events.sort(key=lambda e: (e["first_seen"], e["event_id"]))
    rank = {e["event_id"]: k for k, e in enumerate(events)}
    rows = sorted(by_article.values(), key=lambda r: (rank[r["event_id"]], r["published_at"], r["article_id"]))
    return rows, events


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run(cfg: dict, silver_glob: str = SILVER, out: str | Path = OUT, start: str = "", end: str = "9999",
        encoder=None, log=print, out_dir: str | Path | None = None, cache_dir: str | Path | None = None) -> Path:
    """Ghi bảng vào `out_dir` (mặc định out/<algo_version>), đệm vector ở `cache_dir` (mặc định out/cache). Bộ điều phối
    (serving/pipeline.py) truyền out_dir = thư mục lần chạy để không ghi đè data/events/<algo_version>/."""
    t0 = time.perf_counter()
    arts = load_silver(silver_glob, start, end)
    log(f"{len(arts)} bài Silver ({arts[0]['t'][:10]} → {arts[-1]['t'][:10]})")
    model = str(ROOT / cfg["model"]) if (ROOT / cfg["model"]).exists() else cfg["model"]
    cache = Path(cache_dir or Path(out) / "cache") / f"emb_{cfg['model_version']}.npz"
    vecs = encode({a["id"]: head_text(a["title"], a["sapo"]) for a in arts}, model, cfg["prep"],
                  cache=cache, cache_key=cfg["model_version"], encoder=encoder, log=log)
    E = np.stack([vecs[a["id"]] for a in arts])
    times = np.array([datetime.fromisoformat(a["t"]).timestamp() for a in arts])
    t1 = time.perf_counter()
    labels, stats = cluster(E, times, cfg)
    rows, events = event_tables(arts, E, labels)
    sizes = Counter(e["size"] for e in events)
    out_dir = Path(out_dir) if out_dir else Path(out) / cfg["algo_version"]
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "bai_su_kien.csv", rows)
    _write_csv(out_dir / "su_kien.csv", events)
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "config": cfg,
        "silver_glob": silver_glob, "start": start or None, "end": end if end != "9999" else None,
        "n_articles": len(arts), "first_published": arts[0]["t"], "last_published": arts[-1]["t"],
        "n_events": len(events), "n_events_multi": sum(n for s, n in sizes.items() if s >= 2),
        "n_articles_in_multi": sum(s * n for s, n in sizes.items() if s >= 2),
        "largest_event": max(sizes), "size_hist": {str(k): sizes[k] for k in sorted(sizes)},
        **stats, "seconds_cluster": round(time.perf_counter() - t1, 1), "seconds_total": round(time.perf_counter() - t0, 1),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{len(events)} sự kiện ({manifest['n_events_multi']} sự kiện ≥ 2 bài, lớn nhất {manifest['largest_event']} bài)"
        f" · gom {manifest['seconds_cluster']}s → {out_dir}")
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--silver-glob", default=SILVER)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--start", default="", help="chỉ lấy bài từ ngày này (YYYY-MM-DD)")
    ap.add_argument("--end", default="9999", help="chỉ lấy bài trước ngày này (YYYY-MM-DD)")
    a = ap.parse_args()
    run(load_config(a.config), a.silver_glob, a.out, a.start, a.end)


if __name__ == "__main__":
    main()
