"""Bộ điều phối một lần chạy pipeline sự kiện: Silver → embedding → gom cụm → đặt tên → điểm xu hướng → xuất kết quả.

    uv run --group embed --with pyvi python -m eventrank.serving.pipeline [--steps cluster,name,trend,export]
        [--start YYYY-MM-DD --end YYYY-MM-DD] [--run-id 2026-11-03_v1]
        → data/runs/<run_id>/

Cấu hình: configs/pipeline.yaml (tham chiếu configs/clustering.yaml cho embedding + gom cụm, không chép lại). Không cào
dữ liệu, không ghi R2, không đụng DB — chỉ đọc Silver ở máy và ghi thư mục lần chạy.

Các bước (chạy lại từng bước được, đọc kết quả bước trước trong cùng thư mục lần chạy):
- `cluster`: clustering.pipeline.run → `cum/` (su_kien.csv, bai_su_kien.csv, manifest.json của bước gom cụm). Vector lưu
  đệm chung ở data/events/cache/ → chạy lại chỉ encode bài mới.
- `name`: naming.predict.run → `ten_su_kien.csv` (đệm tên ở data/naming/cache/, ghi tăng dần).
- `trend`: trending.score.run → `xu_huong.csv`, `xu_huong_moc.csv`, `diem_su_kien.csv`. Khoảng mốc = --start/--end nếu
  có, không thì theo cấu hình.
- `export`: `su_kien.csv` gộp, `bai_su_kien.csv`, `events.json` (gọn, cho API/web), `README.md`.

`manifest.json` ghi lại sau mỗi bước: cấu hình đầy đủ (kể cả clustering.yaml đã đọc), các phiên bản (model / algo /
naming / trend), commit git (+ có sửa chưa commit), dấu vân tay Silver (từng file: kích thước + sha256; số bài + sha256
danh sách article_id đã gom cụm), số lượng và thời gian từng bước.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from eventrank.clustering import pipeline as clustering
from eventrank.naming import predict as naming
from eventrank.trending import score as trending

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs/pipeline.yaml"
STEPS = ("cluster", "name", "trend", "export")
EVENT_FIELDS = ["event_id", "ten", "nguon", "size", "n_sources", "sources", "first_seen", "last_seen", "medoid_title",
                "tong_diem", "diem_cao_nhat", "luc_cao_nhat", "so_gio_trong_top10"]


def _path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def load_config(path: str | Path = CONFIG) -> dict:
    """configs/pipeline.yaml + clustering.yaml đã đọc (khoá `clustering.params`) + mặc định của naming / trending."""
    import yaml

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for k in ("clustering", "naming", "trending"):
        if k not in cfg:
            raise ValueError(f"thiếu mục `{k}` trong {path}")
    cfg["clustering"]["params"] = clustering.load_config(_path(cfg["clustering"]["config"]))
    cfg["naming"] = naming.load_config(path)
    cfg["trending"] = trending.load_config(path)
    cfg.setdefault("export", {})
    return cfg


def git_info() -> dict:
    def git(*a: str) -> str:
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=10,
                                  check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    tracked = git("status", "--porcelain", "--untracked-files=no")
    untracked = git("status", "--porcelain", "--untracked-files=all", "--", "src", "configs")
    return {"commit": git("rev-parse", "HEAD") or None, "branch": git("rev-parse", "--abbrev-ref", "HEAD") or None,
            # dirty = có sửa chưa commit, KỂ CẢ file chưa track trong src/ configs/ (code chạy không có trong commit)
            "dirty": bool(tracked or untracked),
            "n_untracked_src_configs": sum(line.startswith("??") for line in untracked.splitlines())}


def silver_files(silver_glob: str) -> list[dict]:
    import glob

    out = []
    for p in sorted(glob.glob(silver_glob)):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out.append({"path": str(Path(p).relative_to(ROOT)) if Path(p).is_relative_to(ROOT) else p,
                    "bytes": Path(p).stat().st_size, "sha256": h.hexdigest()})
    return out


def article_fingerprint(bai_csv: Path) -> dict:
    with open(bai_csv, encoding="utf-8") as f:
        ids = sorted(r["article_id"] for r in csv.DictReader(f))
    return {"n_articles": len(ids), "article_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def export(run_dir: Path, cfg: dict, manifest: dict, log: Callable[[str], None] = print) -> dict:
    """Gộp kết quả các bước → su_kien.csv, bai_su_kien.csv, events.json (README.md ghi sau, khi manifest đủ số)."""
    cum = run_dir / "cum"
    events = _read_csv(cum / "su_kien.csv")
    if not (run_dir / "ten_su_kien.csv").exists():
        raise FileNotFoundError(f"chưa có {run_dir}/ten_su_kien.csv — chạy bước name trước")
    names = {r["event_id"]: r for r in _read_csv(run_dir / "ten_su_kien.csv")}
    missing = [e["event_id"] for e in events if not names.get(e["event_id"], {}).get("ten", "").strip()]
    if missing:
        raise ValueError(f"{len(missing)} sự kiện không có tên (vd. {missing[:3]}) — ten_su_kien.csv lệch với cum/")
    scores = {r["event_id"]: r for r in _read_csv(run_dir / "diem_su_kien.csv")} \
        if (run_dir / "diem_su_kien.csv").exists() else {}
    rows = []
    for e in events:
        n, s = names.get(e["event_id"], {}), scores.get(e["event_id"], {})
        rows.append({**{k: e[k] for k in ("event_id", "size", "n_sources", "sources", "first_seen", "last_seen",
                                          "medoid_title")},
                     "ten": n.get("ten", ""), "nguon": n.get("nguon", ""),
                     **{k: s.get(k, "") for k in ("tong_diem", "diem_cao_nhat", "luc_cao_nhat", "so_gio_trong_top10")}})
    naming.write_csv(run_dir / "su_kien.csv", rows, EVENT_FIELDS)
    shutil.copyfile(cum / "bai_su_kien.csv", run_dir / "bai_su_kien.csv")

    ex = cfg.get("export", {})
    min_size, top = int(ex.get("events_json_min_size", 2)), int(ex.get("events_json_top", 100))
    by_id = {r["event_id"]: r for r in rows}

    def compact(r: dict) -> dict:
        return {"event_id": r["event_id"], "ten": r["ten"], "nguon": r["nguon"], "size": int(r["size"]),
                "n_sources": int(r["n_sources"]), "sources": r["sources"], "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "tong_diem": float(r["tong_diem"]) if r["tong_diem"] else None,
                "diem_cao_nhat": float(r["diem_cao_nhat"]) if r["diem_cao_nhat"] else None,
                "luc_cao_nhat": r["luc_cao_nhat"] or None,
                "so_gio_trong_top10": int(r["so_gio_trong_top10"]) if r["so_gio_trong_top10"] else 0}

    latest = None
    if (run_dir / "xu_huong.csv").exists():
        xu = _read_csv(run_dir / "xu_huong.csv")
        if xu:
            # mốc cuối có ≥ min_candidates sự kiện (cuối khoảng dữ liệu chỉ còn lác đác 1–2 sự kiện); không có thì mốc cuối
            per_t: dict[str, int] = {}
            for r in xu:
                per_t[r["t"]] = per_t.get(r["t"], 0) + 1
            need = int(ex.get("latest_min_candidates", 10))
            full = [t for t, n in per_t.items() if n >= need]
            t_last = max(full) if full else max(per_t)
            latest = {"t": t_last, "top": [{"hang": int(r["hang"]), "event_id": r["event_id"],
                                            "ten": by_id[r["event_id"]]["ten"], "score": float(r["score"]),
                                            "so_bai_den_t": int(r["so_bai_den_t"]), "so_bao": int(r["so_bao"])}
                                           for r in xu if r["t"] == t_last]}
    # "nổi bật" = tổng điểm theo giờ (tích phân), không theo điểm đỉnh: điểm đỉnh thưởng sự kiện mới nổ, bỏ sót sự kiện lớn
    ranked = sorted((r for r in rows if r["tong_diem"]), key=lambda r: (-float(r["tong_diem"]), r["event_id"]))[:top]
    doc = {"run_id": run_dir.name, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "versions": manifest.get("versions", {}),
           "ghi_chu": "Điểm xu hướng CHƯA được đánh giá (chưa có nhãn 'Xem nhiều'); tên do ViT5 sinh, chưa người duyệt.",
           "xu_huong_moi_nhat": latest,
           "noi_bat": [compact(r) for r in ranked],
           "su_kien": [compact(r) for r in rows if int(r["size"]) >= min_size]}
    (run_dir / "events.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    log(f"xuất {len(rows)} sự kiện ({len(doc['su_kien'])} sự kiện ≥ {min_size} bài vào events.json) → {run_dir}")
    return {"n_events": len(rows), "n_events_json": len(doc["su_kien"]), "n_noi_bat": len(doc["noi_bat"])}


def _readme(run_id: str, m: dict, n_events: int, n_json: int) -> str:
    v = m.get("versions", {})
    st = m.get("steps", {})
    nm = st.get("name", {}).get("stats", {})
    return f"""# Lần chạy pipeline sự kiện `{run_id}`

Sinh bằng `python -m eventrank.serving.pipeline` (commit {m.get('git', {}).get('commit')}, có sửa chưa commit:
{m.get('git', {}).get('dirty')}). Cấu hình đầy đủ, dấu vân tay Silver, thời gian từng bước: `manifest.json`.

Phiên bản: embedding `{v.get('model_version')}` · gom cụm `{v.get('algo_version')}` · đặt tên `{v.get('naming_version')}` ·
xu hướng `{v.get('trend_version')}`. Silver: {m.get('silver', {}).get('n_articles')} bài → {n_events} sự kiện
({n_json} sự kiện ≥ 2 bài). Nguồn tên: {nm.get('nguon')} · lý do rơi về medoid: {nm.get('ly_do_fallback')}.

| File | Nội dung |
|---|---|
| `su_kien.csv` | mỗi sự kiện một dòng: event_id, ten, nguon (model/medoid/title), size, n_sources, sources, first_seen, last_seen, medoid_title, tong_diem, diem_cao_nhat, luc_cao_nhat, so_gio_trong_top10 |
| `bai_su_kien.csv` | mỗi bài một dòng: event_id, article_id, published_at, source, category, title, is_medoid |
| `ten_su_kien.csv` | tên + nguồn + lý do (rơi về medoid / tiêu đề rút gọn) + tên gốc của mô hình nếu bị thay |
| `xu_huong.csv` | top-K mỗi giờ theo điểm xu hướng (công thức `{m.get('config', {}).get('trending', {}).get('formula')}`, xem eventrank/trending/score.py) |
| `xu_huong_moc.csv` | 3 xếp hạng mốc cùng tập ứng viên: số bài thô, số báo thô, số bài 3h |
| `diem_su_kien.csv` | tổng điểm theo giờ (tiêu chí "nổi bật"), điểm cao nhất, lúc cao nhất, số giờ trong top 10 |
| `events.json` | bản gọn cho API/web: sự kiện ≥ 2 bài, top xu hướng mốc cuối có ≥ 10 sự kiện, 100 sự kiện tổng điểm cao nhất |
| `cum/` | đầu ra nguyên bản của bước gom cụm |

⚠ Điểm xu hướng **chưa được đánh giá** (chưa có nhãn "Xem nhiều"); α, H chọn tạm. Tên sự kiện do mô hình sinh, chưa
người duyệt; kiểm tra trung thực chỉ là phép thô (số, từ viết hoa, lặp thực thể) — không bắt được tên sai nghĩa khi mọi
từ đều có trong cụm (kiểm tra độc lập ước ~12% tên mô hình sai nghĩa/bịa).

⚠ **Giới hạn rò rỉ (chưa sửa):** đặc trưng xu hướng tại t chỉ dùng bài ≤ t, nhưng cụm được gom trên TOÀN kho (bài sau t có
thể đã "bắc cầu" gộp các bài ≤ t) và tên sinh từ cả cụm. Dùng cho demo offline; KHÔNG dùng làm số đánh giá theo thời gian
thực — khi có nhãn "Xem nhiều" phải gom cụm lại chỉ với bài ≤ t.

⚠ Giao thức tập test đặt tên: run này chứa tên ViT5 cho cửa sổ 14–15/09 (176 cụm vàng cần tên người viết mù) — người viết
tên mù không mở `ten_su_kien.csv`, `su_kien.csv`, `events.json`, `xu_huong*.csv` của run.
"""


def run(cfg: dict, run_id: str, steps: list[str], start: str = "", end: str = "", silver_glob: str = "",
        runs_root: str | Path | None = None, encoder=None, generator=None,
        log: Callable[[str], None] = print, force: bool = False) -> Path:
    """Chạy các bước `steps` vào runs_root/run_id. Run đã tồn tại (có manifest.json): chạy lại một số bước KHÔNG gồm
    `cluster` thì được (tiếp tục / làm lại tên, xu hướng, xuất); có `cluster` (ghi đè cụm) thì phải `force=True`."""
    silver_glob = silver_glob or str(_path(cfg.get("silver_glob", "data/lake/silver/*/*.jsonl")))
    run_dir = Path(runs_root or _path(cfg.get("run_root", "data/runs"))) / run_id
    mpath = run_dir / "manifest.json"
    if mpath.exists() and "cluster" in steps and not force:
        raise FileExistsError(f"{run_dir} đã có — dùng run_id khác, --force để ghi đè, hoặc --steps không gồm cluster")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {"run_id": run_id, "steps": {}}
    cc, nc, tc = cfg["clustering"]["params"], cfg["naming"], cfg["trending"]
    if "cluster" in steps:
        manifest["range"] = {"start": start or None, "end": end or None}
    else:                                                            # chạy lại một phần: giữ khoảng của bước gom cụm
        rg = manifest.get("range") or {}
        start, end = start or rg.get("start") or "", end or rg.get("end") or ""
    manifest.update({"config": cfg, "git": git_info(), "silver_glob": silver_glob,
                     "versions": {"model_version": cc["model_version"], "algo_version": cc["algo_version"],
                                  "naming_version": nc["naming_version"], "trend_version": tc["trend_version"]}})

    def save() -> None:
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    cum = run_dir / "cum"
    for step in STEPS:
        if step not in steps:
            continue
        if step != "cluster" and not (cum / "su_kien.csv").exists():
            raise FileNotFoundError(f"chưa có {cum}/su_kien.csv — chạy bước cluster trước")
        log(f"── bước {step} ──")
        t0 = time.perf_counter()
        info: dict = {}
        if step == "cluster":
            clustering.run(cc, silver_glob, start=start, end=end or "9999", encoder=encoder, log=log, out_dir=cum,
                           cache_dir=_path(cfg["clustering"].get("cache_dir", "data/events/cache")))
            cm = json.loads((cum / "manifest.json").read_text(encoding="utf-8"))
            info = {k: cm[k] for k in ("n_articles", "n_events", "n_events_multi", "largest_event", "first_published",
                                       "last_published")}
            manifest["silver"] = {"files": silver_files(silver_glob), **article_fingerprint(cum / "bai_su_kien.csv")}
        elif step == "name":
            info = {"stats": naming.run(cum, nc, run_dir, silver_glob, generator=generator, log=log)}
        elif step == "trend":
            meta = trending.run(cum, tc, run_dir, start, end, log=log)
            info = {k: v for k, v in meta.items()}
        else:
            info = export(run_dir, cfg, manifest, log)
        manifest["steps"][step] = {**info, "seconds": round(time.perf_counter() - t0, 1),
                                   "finished_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        save()
    if "export" in steps:                                            # README dùng số của mọi bước
        (run_dir / "README.md").write_text(
            _readme(run_id, manifest, manifest["steps"]["export"]["n_events"],
                    manifest["steps"]["export"]["n_events_json"]), encoding="utf-8")
    log(f"xong → {run_dir}")
    return run_dir


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--steps", default=",".join(STEPS), help="các bước, cách nhau bằng dấu phẩy")
    ap.add_argument("--start", default="", help="chỉ lấy bài từ ngày này (YYYY-MM-DD); cũng là mốc đầu xu hướng")
    ap.add_argument("--end", default="", help="chỉ lấy bài trước ngày này (YYYY-MM-DD); cũng là mốc cuối xu hướng")
    ap.add_argument("--run-id", default="", help="mặc định <hôm nay>_<algo_version>")
    ap.add_argument("--silver-glob", default="")
    ap.add_argument("--force", action="store_true", help="cho phép ghi đè run_id đã có khi chạy bước cluster")
    ap.add_argument("--max-generate", type=int, default=None,
                    help="bước name dừng (trước khi nạp mô hình) nếu cần sinh nhiều hơn N cụm; 0 = chỉ dùng đệm")
    a = ap.parse_args()
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    bad = set(steps) - set(STEPS)
    if bad:
        ap.error(f"bước không hợp lệ: {sorted(bad)} (chọn trong {', '.join(STEPS)})")
    cfg = load_config(a.config)
    if a.max_generate is not None:
        cfg["naming"]["max_generate"] = a.max_generate
    today = datetime.now().astimezone().date().isoformat()
    run_id = a.run_id or f"{today}_{cfg['clustering']['params']['algo_version']}"
    run(cfg, run_id, steps, a.start, a.end, a.silver_glob, log=lambda m: print(m, flush=True),   # log sống khi nohup
        force=a.force)


if __name__ == "__main__":
    main()
