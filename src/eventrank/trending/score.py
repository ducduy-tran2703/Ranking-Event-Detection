"""Điểm xu hướng sự kiện theo thời gian (docs/tong-hop.md mục 9.3) → bảng xu hướng mỗi giờ.

    uv run --group embed python -m eventrank.trending.score            # data/events/v1/ → xu_huong*.csv, diem_su_kien.csv

Hai công thức, chọn bằng `formula` trong cấu hình; tại mốc t (giờ Việt Nam, mặc định mỗi giờ 01/08 → 20/09/2026):

    decay   (t2, mặc định):  score(e, t) = n_hd(e, t)^α · log(1 + v_dec(e, t) / b_W(t))
                             v_dec(e, t) = Σ_{bài i của e, t_i ≤ t} 2^(−(t − t_i) / H),  H = `half_life_hours` (3h)
    gravity (t1, để so):     score(e, t) = n_hd(e, t)^α · log(1 + so_bai_3h / b_W(t)) / (tuoi(e, t) + 2)^G

Vì sao đổi sang t2 (kiểm tra độc lập 03/11/2026, data/temp/kiem_tra_pipeline/BAO_CAO.md mục N1): ở t1 số hạng tuổi tính
từ bài ĐẦU TIÊN lấn át vận tốc — 52,9% ô top-10 là sự kiện mới 2 bài, sự kiện ≥ 5 bài/3h nằm ngoài top-3 ở 52,8% số cặp
(mốc, sự kiện). t2 bỏ phạt tuổi sự kiện; mỗi BÀI tự giảm trọng số theo tuổi của chính nó (nửa đời H), nên sự kiện lớn đang
được đưa tin dồn dập giữ hạng cao, còn sự kiện ngừng có bài mới tự rơi xuống.

CHỈ dùng bài của sự kiện có published_at ≤ t (không rò rỉ tương lai ở ĐẶC TRƯNG; tests/trending kiểm điều này):
- `so_bai_3h` = số bài của e trong cửa sổ (t − W, t], W = `window_hours` (3h). Ứng viên tại t = sự kiện có ≥ 1 bài trong
  cửa sổ và ≥ `min_so_bai` bài đến t (cả hai công thức).
- **Mức nền theo giờ trong ngày** b[h], h = 0..23 (giờ Việt Nam): số bài của TOÀN kho đăng trong khung giờ h trong khoảng
  [baseline_start, baseline_end), cộng 1 (tránh chia 0 ở giờ trống), rồi chia cho trung bình 24 giá trị → trung bình
  b = 1; b[h] > 1 là giờ báo đăng nhiều hơn mức trung bình. Mức nền của cửa sổ b_W(t) = trung bình b của W khung giờ
  phủ cửa sổ (giờ của t − 1h, t − 2h, t − 3h khi t tròn giờ). Trong một mốc b_W giống nhau cho mọi sự kiện nên gần như
  không đổi thứ hạng; nó chủ yếu làm điểm so được giữa các giờ (tong_diem, diem_cao_nhat).
- **Vận tốc chuẩn hoá** (cột `van_toc`) = v / b_W(t) (decay: v = v_dec; gravity: v = so_bai_3h).
- **Số nguồn hiệu dụng** n_hd(e, t): Silver chưa có `dup_group_id` → dùng số báo khác nhau, giảm trọng số báo "chép":
  mỗi báo có trọng số 1, trừ khi MỌI bài của báo đó (đến t) đều trùng nguyên văn tiêu đề (chữ thường, bỏ dấu câu) với
  một bài của báo KHÁC đăng trước nó trong cùng sự kiện → trọng số `dup_weight` (0,5). Đánh dấu "chép" chỉ nhìn bài đăng
  trước nên cũng không rò rỉ tương lai.
- **Tuổi** tuoi(e, t) = số giờ từ bài đầu tiên của e đến t (chỉ dùng trong gravity; vẫn ghi ra để xem).

**Hạn chế đã biết (V1 — CHƯA sửa):** đặc trưng sạch, nhưng (a) THÀNH VIÊN CỤM do gom cụm chạy trên TOÀN kho (agglo
average-linkage, cửa sổ 48h) → tại t, cách gộp các bài ≤ t có thể đã bị bài đăng SAU t "bắc cầu"; (b) tên/medoid sinh từ cả
cụm; (c) mức nền tính trên cả giai đoạn. Chấp nhận cho demo offline; KHÔNG dùng bảng này làm số đánh giá "theo thời gian
thực" — khi có nhãn "Xem nhiều" phải gom cụm lại chỉ với bài ≤ t (hoặc gom cụm tăng dần). Ngoài ra chưa chuẩn hoá theo
lượng bài tăng dần theo ngày (tháng 9 dày gấp ~1,9 tháng 8) và chưa tách bảng theo chuyên mục.

**CHƯA đánh giá được**: chưa có nhãn "Xem nhiều"/"Đọc nhiều" (mục 9.3) → α, H, W, G chọn tạm, chưa chỉnh. Để so sau này,
`xu_huong_moc.csv` ghi kèm 3 xếp hạng mốc trên CÙNG tập ứng viên: số bài thô đến t (`so_bai`), số báo thô (`so_bao`),
số bài trong cửa sổ 3h (`so_bai_3h`).

Đầu ra (ghi ở máy):
- `xu_huong.csv`: top-K mỗi mốc — t, hang, event_id, score, so_bai_den_t, so_bai_3h, so_bao, n_nguon_hd, van_toc, tuoi_gio.
- `xu_huong_moc.csv`: t, phuong_phap (so_bai | so_bao | so_bai_3h), hang, event_id, gia_tri.
- `diem_su_kien.csv`: event_id, tong_diem (Σ_t score · step_hours = "tích phân" điểm theo giờ — tiêu chí xếp "nổi bật",
  thưởng cả độ nóng lẫn độ bền), diem_cao_nhat, luc_cao_nhat, so_gio_trong_top10; sắp theo tong_diem giảm dần.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from bisect import bisect_right
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs/pipeline.yaml"
VN = timezone(timedelta(hours=7))
DEFAULTS = {"trend_version": "t2", "formula": "decay", "half_life_hours": 3.0, "alpha": 1.0, "gravity": 1.5,
            "window_hours": 3, "step_hours": 1, "top_k": 20,
            "top_n_hours": 10, "min_so_bai": 2, "dup_weight": 0.5, "start": "2026-08-01", "end": "2026-09-20",
            "baseline_start": "2026-08-01", "baseline_end": "2026-09-20"}
_PUNCT = re.compile(r"[^\w\s]")


def load_config(path: str | Path = CONFIG) -> dict:
    """Mục `trending` của configs/pipeline.yaml, bổ sung giá trị mặc định."""
    import yaml

    with open(path, encoding="utf-8") as f:
        return {**DEFAULTS, **(yaml.safe_load(f) or {}).get("trending", {})}


def day(s: str) -> datetime:
    """'YYYY-MM-DD' → 00:00 giờ Việt Nam ngày đó."""
    return datetime.fromisoformat(str(s)[:10]).replace(tzinfo=VN)


def _norm_title(s: str) -> str:
    return " ".join(_PUNCT.sub(" ", unicodedata.normalize("NFC", s or "").lower()).split())


def load_articles(path: str | Path) -> list[dict]:
    """bai_su_kien.csv → [{event_id, ts (giây epoch), source, title}]."""
    with open(path, encoding="utf-8") as f:
        return [{"event_id": r["event_id"], "ts": datetime.fromisoformat(r["published_at"]).timestamp(),
                 "source": r["source"], "title": r.get("title", "")} for r in csv.DictReader(f)]


def hourly_baseline(ts: list[float], start: datetime, end: datetime) -> list[float]:
    """Mức nền b[0..23] theo giờ trong ngày (giờ VN) trên [start, end): đếm bài + 1, chuẩn hoá trung bình = 1."""
    lo, hi = start.timestamp(), end.timestamp()
    cnt = [1.0] * 24
    for x in ts:
        if lo <= x < hi:
            cnt[datetime.fromtimestamp(x, VN).hour] += 1
    mean = sum(cnt) / 24
    return [c / mean for c in cnt]


class EventIndex:
    """Bài của mọi sự kiện, sắp theo thời gian, để tính đặc trưng tại t bằng tìm kiếm nhị phân."""

    def __init__(self, arts: list[dict]):
        by: dict[str, list[dict]] = {}
        for a in arts:
            by.setdefault(a["event_id"], []).append(a)
        self.ev: dict[str, dict] = {}
        for eid, xs in by.items():
            xs.sort(key=lambda a: a["ts"])
            first_by_title: dict[str, str] = {}                    # tiêu đề chuẩn hoá → báo đăng đầu tiên
            copy = []
            for a in xs:
                k = _norm_title(a["title"])
                src0 = first_by_title.setdefault(k, a["source"]) if k else a["source"]
                copy.append(bool(k) and src0 != a["source"])         # trùng tiêu đề bài báo khác đăng TRƯỚC
            self.ev[eid] = {"ts": [a["ts"] for a in xs], "src": [a["source"] for a in xs], "copy": copy}
        order = sorted((a["ts"], a["event_id"]) for a in arts)
        self.ts = [x[0] for x in order]
        self.eid = [x[1] for x in order]

    def features(self, eid: str, t: float, window: float, dup_weight: float) -> dict:
        e = self.ev[eid]
        k = bisect_right(e["ts"], t)                                 # chỉ bài có published_at ≤ t
        w: dict[str, float] = {}
        for s, c in zip(e["src"][:k], e["copy"][:k]):
            w[s] = max(w.get(s, 0.0), dup_weight if c else 1.0)
        return {"so_bai_den_t": k, "so_bai_3h": k - bisect_right(e["ts"], t - window, 0, k), "so_bao": len(w),
                "n_nguon_hd": sum(w.values()), "tuoi_gio": (t - e["ts"][0]) / 3600 if k else 0.0}


def window_baseline(b: list[float], t: datetime, window_hours: float) -> float:
    n = max(1, math.ceil(window_hours))
    return sum(b[(t - timedelta(hours=j)).hour] for j in range(1, n + 1)) / n


def score_at(idx: EventIndex, t: datetime, cfg: dict, b: list[float]) -> list[dict]:
    """Mọi sự kiện có ≥ 1 bài trong (t − W, t] và ≥ min_so_bai bài đến t, sắp theo score giảm dần."""
    tt, win = t.timestamp(), cfg["window_hours"] * 3600
    cand = set(idx.eid[bisect_right(idx.ts, tt - win):bisect_right(idx.ts, tt)])
    bw = window_baseline(b, t, cfg["window_hours"])
    formula = cfg.get("formula", "decay")
    if formula not in ("decay", "gravity"):
        raise ValueError(f"formula phải là decay hoặc gravity, không phải {formula!r}")
    half = float(cfg.get("half_life_hours", 3.0)) * 3600
    rows = []
    for eid in cand:
        f = idx.features(eid, tt, win, cfg["dup_weight"])
        if f["so_bai_den_t"] < cfg["min_so_bai"] or f["so_bai_3h"] == 0:
            continue
        if formula == "decay":
            ts = idx.ev[eid]["ts"][:f["so_bai_den_t"]]                 # chỉ bài ≤ t
            v = sum(2.0 ** (-(tt - x) / half) for x in ts) / bw
            s = f["n_nguon_hd"] ** cfg["alpha"] * math.log1p(v)
        else:
            v = f["so_bai_3h"] / bw
            s = f["n_nguon_hd"] ** cfg["alpha"] * math.log1p(v) / (f["tuoi_gio"] + 2) ** cfg["gravity"]
        rows.append({"event_id": eid, "score": s, "van_toc": v, **f})
    rows.sort(key=lambda r: (-r["score"], -r["so_bai_3h"], r["event_id"]))
    return rows


def steps(start: datetime, end: datetime, step_hours: float) -> list[datetime]:
    """Các mốc t = start + k·step (k ≥ 1), t ≤ end."""
    out, t = [], start + timedelta(hours=step_hours)
    while t <= end:
        out.append(t)
        t += timedelta(hours=step_hours)
    return out


def compute(arts: list[dict], cfg: dict, start: datetime | None = None, end: datetime | None = None,
            log: Callable[[str], None] = print) -> dict:
    """→ {xu_huong, moc, diem, meta}: bảng xu hướng top-K mỗi mốc, 2 xếp hạng mốc, điểm từng sự kiện."""
    start = start or day(cfg["start"])
    end = end or day(cfg["end"])
    b = hourly_baseline([a["ts"] for a in arts], day(cfg["baseline_start"]), day(cfg["baseline_end"]))
    idx = EventIndex(arts)
    K, topn = int(cfg["top_k"]), int(cfg["top_n_hours"])
    xu, moc, best, top_hours, total = [], [], {}, {}, {}
    ts = steps(start, end, cfg["step_hours"])
    for t in ts:
        rows = score_at(idx, t, cfg, b)
        tl = t.isoformat()
        for r_, r in enumerate(rows, 1):
            if r_ <= K:
                xu.append({"t": tl, "hang": r_, "event_id": r["event_id"], "score": round(r["score"], 6),
                           "so_bai_den_t": r["so_bai_den_t"], "so_bai_3h": r["so_bai_3h"], "so_bao": r["so_bao"],
                           "n_nguon_hd": r["n_nguon_hd"], "van_toc": round(r["van_toc"], 4),
                           "tuoi_gio": round(r["tuoi_gio"], 2)})
            if r_ <= topn:
                top_hours[r["event_id"]] = top_hours.get(r["event_id"], 0) + cfg["step_hours"]
            if r["score"] > best.get(r["event_id"], (0.0, ""))[0]:
                best[r["event_id"]] = (r["score"], tl)
            total[r["event_id"]] = total.get(r["event_id"], 0.0) + r["score"] * cfg["step_hours"]
        for name, key in (("so_bai", lambda r: (-r["so_bai_den_t"], -r["so_bai_3h"], r["event_id"])),
                          ("so_bao", lambda r: (-r["so_bao"], -r["so_bai_den_t"], r["event_id"])),
                          ("so_bai_3h", lambda r: (-r["so_bai_3h"], -r["so_bao"], r["event_id"]))):
            for r_, r in enumerate(sorted(rows, key=key)[:K], 1):
                moc.append({"t": tl, "phuong_phap": name, "hang": r_, "event_id": r["event_id"], "gia_tri": r[
                    {"so_bai": "so_bai_den_t", "so_bao": "so_bao", "so_bai_3h": "so_bai_3h"}[name]]})
    diem = sorted(({"event_id": e, "tong_diem": round(total[e], 6), "diem_cao_nhat": round(s, 6), "luc_cao_nhat": tl,
                    "so_gio_trong_top10": top_hours.get(e, 0)} for e, (s, tl) in best.items()),
                  key=lambda r: (-r["tong_diem"], r["event_id"]))
    meta = {"trend_version": cfg["trend_version"], "formula": cfg.get("formula", "decay"),
            "start": start.isoformat(), "end": end.isoformat(),
            "n_steps": len(ts), "n_events_scored": len(diem), "n_rows": len(xu),
            "baseline_hour": [round(x, 3) for x in b],
            "n_copy_articles": sum(sum(e["copy"]) for e in idx.ev.values())}
    log(f"xu hướng: {len(ts)} mốc ({meta['start'][:16]} → {meta['end'][:16]}), {len(diem)} sự kiện có điểm, "
        f"{meta['n_copy_articles']} bài trùng tiêu đề báo khác")
    return {"xu_huong": xu, "moc": moc, "diem": diem, "meta": meta}


XU_FIELDS = ["t", "hang", "event_id", "score", "so_bai_den_t", "so_bai_3h", "so_bao", "n_nguon_hd", "van_toc",
             "tuoi_gio"]
MOC_FIELDS = ["t", "phuong_phap", "hang", "event_id", "gia_tri"]
DIEM_FIELDS = ["event_id", "tong_diem", "diem_cao_nhat", "luc_cao_nhat", "so_gio_trong_top10"]


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def run(events_dir: str | Path, cfg: dict, out_dir: str | Path | None = None, start: str = "", end: str = "",
        log: Callable[[str], None] = print) -> dict:
    """bai_su_kien.csv của `events_dir` → out_dir/{xu_huong.csv, xu_huong_moc.csv, diem_su_kien.csv}. Trả meta."""
    out_dir = Path(out_dir or events_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = compute(load_articles(Path(events_dir) / "bai_su_kien.csv"), cfg,
                  day(start) if start else None, day(end) if end else None, log)
    _write(out_dir / "xu_huong.csv", res["xu_huong"], XU_FIELDS)
    _write(out_dir / "xu_huong_moc.csv", res["moc"], MOC_FIELDS)
    _write(out_dir / "diem_su_kien.csv", res["diem"], DIEM_FIELDS)
    log(f"→ {out_dir}/{{xu_huong.csv, xu_huong_moc.csv, diem_su_kien.csv}}")
    return res["meta"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--events-dir", default=str(ROOT / "data/events/v1"))
    ap.add_argument("--out", default="", help="mặc định = --events-dir")
    ap.add_argument("--start", default="", help="mốc đầu (YYYY-MM-DD), mặc định trong cấu hình")
    ap.add_argument("--end", default="", help="mốc cuối (YYYY-MM-DD), mặc định trong cấu hình")
    a = ap.parse_args()
    meta = run(a.events_dir, load_config(a.config), a.out or None, a.start, a.end)
    print(json.dumps({k: v for k, v in meta.items() if k != "baseline_hour"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
