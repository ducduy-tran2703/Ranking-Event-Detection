"""Kết quả một lần chạy pipeline sự kiện (`data/runs/<run_id>/`) nạp vào RAM để API phục vụ web demo.

Chỉ ĐỌC thư mục lần chạy ở máy (không đọc R2, không ghi gì). Chọn thư mục:
- `EVENTS_RUN_DIR` nếu đặt (đường dẫn tương đối tính từ gốc repo hoặc tuyệt đối);
- không thì lần chạy ĐẦY ĐỦ mới nhất trong `data/runs/`: có `manifest.json` + `su_kien.csv`, manifest không giới hạn
  `--start/--end` (`range` rỗng — bỏ qua run thử một lát cắt), `finished_at` muộn nhất trong `manifest.steps` (KHÔNG theo
  thời điểm sửa file: chép/chạm file không làm demo tự đổi run).

Nạp `su_kien.csv`, `bai_su_kien.csv`, `xu_huong.csv`, `manifest.json` (run thật: ~20 nghìn sự kiện, ~29 nghìn bài, ~14
nghìn dòng xu hướng). KHÔNG phục vụ `events.json` hay `ten_su_kien.csv` (chứa tên mô hình chưa lọc).

**Ẩn tên cửa sổ tập test đặt tên** (`EVENTS_HIDE_NAMES_WINDOW`, mặc định `2026-09-14..2026-09-15`, giờ Việt Nam, gồm cả
hai ngày; KHÔNG đặt hoặc RỖNG = mặc định; chỉ giá trị `off` mới tắt, kèm cảnh báo trong log): 176 cụm vàng 14–15/09 cần
tên người viết MÙ trước khi xem tên mô hình. Sự kiện bị ẩn → tên hiển thị = `medoid_title`, `nguon_ten = "an"`,
`ten_bi_an = True`. Bị ẩn khi:
1. khoảng [first_seen, last_seen] giao cửa sổ; hoặc
2. ở NGOÀI cửa sổ, tên mô hình GẦN TRÙNG một "tên bí mật": Jaccard âm tiết ≥ `NEAR_DUP_JACCARD` (0,6; trùng nguyên văn
   = 1). Tên bí mật = tên mô hình của sự kiện trong cửa sổ + tên mô hình bị loại (`ten_mo_hinh` trong `ten_su_kien.csv`,
   chỉ đọc lúc nạp để so) của các sự kiện đó. Lý do: kiểm tra độc lập 04/11/2026 (data/temp/kiem_tra_web/BAO_CAO.md, V1)
   thấy tên ngoài cửa sổ chung 9/12 âm tiết với tên ẩn — đủ để "neo" người viết mù.
Tên mô hình của sự kiện bị ẩn và tập tên bí mật bị BỎ NGAY LÚC NẠP (không giữ trong RAM) → không endpoint nào, kể cả tìm
kiếm, chạm tới được. Tiêu đề BÀI BÁO (văn bản nguồn) vẫn hiển thị — tên mô hình chép nguyên một tiêu đề bài thì chuỗi đó
vẫn có trong danh sách bài.

**Chuỗi điểm xu hướng của một sự kiện** (trang chi tiết): `xu_huong.csv` chỉ có top-20 mỗi giờ nên không đủ vẽ đường.
Điểm của sự kiện e tại t chỉ phụ thuộc bài của chính e, mức nền theo giờ b và tham số → tính lại bằng đúng
`trending.score.score_at` trên một `EventIndex` chỉ chứa bài của e, cùng cấu hình (`manifest.config.trending`) và cùng mức
nền (tính lại từ `bai_su_kien.csv` của run như bước trend đã làm; so với `manifest.steps.trend.baseline_hour`). Mốc theo
lưới của run (start + k·step). Không phải ứng viên tại t (không có bài trong 3h, hoặc < min_so_bai bài) → điểm 0, như cách
bước trend cộng `tong_diem`.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import re
import time
import unicodedata
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from eventrank.trending import score as trending

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
RUNS_ROOT = ROOT / "data/runs"
VN = trending.VN
EVENT_ID_PATTERN = r"^E\d{8}-[0-9a-f]{8}$"
DEFAULT_HIDE_WINDOW = "2026-09-14..2026-09-15"
HIDE_OFF = "off"
NEAR_DUP_JACCARD = 0.6
"""Ngưỡng tên gần trùng: |A ∩ B| / |A ∪ B| trên TẬP âm tiết (chữ thường, bỏ dấu câu, bỏ dấu thanh — `syllables`), đúng
định nghĩa của `data/temp/kiem_tra_web/do_lo_ten.py` (gan_trung.csv). Run v2: ≥ 0,6 → 26 sự kiện ngoài cửa sổ bị ẩn thêm (2 trùng hẳn)
(kiểm tra độc lập ước 18 vì bỏ các tên ẩn vốn là đoạn trích tiêu đề bài; ở đây giữ cả chúng cho chắc). Chỉ số khác —
|A ∩ B| / |B| (tỉ lệ âm tiết của tên ẩn có trong tên hiển thị) — cùng ngưỡng ẩn tới 116 sự kiện, phần lớn chỉ chung chủ
đề, nên không dùng."""
SORTS = ("hot", "newest", "size")
MAX_SERIES_POINTS = 24 * 21          # sự kiện dài nhất của run v2 ~60 giờ; chặn trên phòng run khác
NO_RUN_MESSAGE = ("Chưa có kết quả pipeline sự kiện: chạy `make pipeline` (→ data/runs/<run_id>/) "
                  "hoặc đặt EVENTS_RUN_DIR rồi khởi động lại API.")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PUNCT = re.compile(r"[^\w\s]")


class RunNotFound(FileNotFoundError):
    pass


class HideWindowError(ValueError):
    """EVENTS_HIDE_NAMES_WINDOW sai cú pháp → phần sự kiện trả 503 (an toàn: không phục vụ tên nào)."""


def fold(s: str) -> str:
    """Chuỗi để tìm kiếm: chữ thường, bỏ dấu tiếng Việt ("Hà Nội" → "ha noi")."""
    s = unicodedata.normalize("NFD", (s or "").lower().replace("đ", "d").replace("Đ", "d"))
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def syllables(s: str) -> frozenset[str]:
    """Tập âm tiết để so tên gần trùng: chữ thường, bỏ dấu câu, bỏ dấu thanh ("Hà Nội: mưa!" → {ha, noi, mua})."""
    return frozenset(fold(_PUNCT.sub(" ", unicodedata.normalize("NFC", s or ""))).split())


def syllable_jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def rel_label(path: str | Path) -> str:
    """Đường dẫn để HIỂN THỊ (thông báo lỗi trả cho trình duyệt): tương đối theo gốc repo, không thì chỉ tên thư mục."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return p.name


def _finished_at(manifest: dict) -> datetime | None:
    times = []
    for st in (manifest.get("steps") or {}).values():
        try:
            times.append(datetime.fromisoformat(st["finished_at"]))
        except (KeyError, TypeError, ValueError):
            continue
    return max(times, default=None)


def find_run_dir(runs_root: str | Path = RUNS_ROOT) -> Path | None:
    """Lần chạy ĐẦY ĐỦ mới nhất: có manifest.json + su_kien.csv, `range` không giới hạn, `finished_at` muộn nhất."""
    root = Path(runs_root)
    if not root.is_dir():
        return None
    best: tuple[datetime, str, Path] | None = None
    for d in root.iterdir():
        if not ((d / "manifest.json").is_file() and (d / "su_kien.csv").is_file()):
            continue
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rg = m.get("range") or {}
        fin = _finished_at(m)
        if rg.get("start") or rg.get("end") or fin is None:       # run thử một lát cắt / chưa xong bước nào
            continue
        if best is None or (fin, d.name) > best[:2]:
            best = (fin, d.name, d)
    return best[2] if best else None


def parse_hide_window(value: str | None) -> tuple[datetime, datetime] | None:
    """'YYYY-MM-DD..YYYY-MM-DD' (hoặc một ngày) → [00:00 ngày đầu, 00:00 ngày SAU ngày cuối) giờ VN.

    Không đặt / rỗng → cửa sổ MẶC ĐỊNH (một dòng `EVENTS_HIDE_NAMES_WINDOW=` vô tình trong .env không được làm lộ tên).
    Chỉ `off` (không phân biệt hoa thường) mới tắt → None, kèm cảnh báo trong log."""
    value = (value or "").strip() or DEFAULT_HIDE_WINDOW
    if value.lower() == HIDE_OFF:
        log.warning("EVENTS_HIDE_NAMES_WINDOW=off: TẮT ẩn tên — tên mô hình của cửa sổ tập test đặt tên sẽ hiển thị")
        return None
    a, _, b = value.partition("..")
    a, b = a.strip(), (b.strip() or a.strip())
    if not (_DATE.match(a) and _DATE.match(b)):
        raise HideWindowError(f"EVENTS_HIDE_NAMES_WINDOW không hợp lệ: {value!r} (dạng YYYY-MM-DD..YYYY-MM-DD hoặc off)")
    try:
        lo, hi = trending.day(a), trending.day(b) + timedelta(days=1)
    except ValueError as exc:                                   # 2026-02-30
        raise HideWindowError(f"EVENTS_HIDE_NAMES_WINDOW không hợp lệ: {value!r} ({exc})") from exc
    if hi <= lo:
        raise HideWindowError(f"EVENTS_HIDE_NAMES_WINDOW: ngày cuối trước ngày đầu ({value!r})")
    return lo, hi


def _f(x: str) -> float | None:
    return float(x) if x not in ("", None) else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, VN).isoformat()


@dataclass(slots=True)
class Event:
    event_id: str
    ten: str                    # tên ĐANG HIỂN THỊ (đã thay bằng medoid_title nếu bị ẩn)
    nguon_ten: str              # model | medoid | title | an
    ten_bi_an: bool
    size: int
    n_sources: int
    sources: dict[str, int]
    first_seen: str
    last_seen: str
    first_ts: float
    last_ts: float
    medoid_title: str
    tong_diem: float | None
    diem_cao_nhat: float | None
    luc_cao_nhat: str | None
    so_gio_trong_top10: int
    key: str                    # chuỗi tìm kiếm = fold(tên hiển thị + medoid_title)

    def summary(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "ten": self.ten, "nguon_ten": self.nguon_ten, "ten_bi_an": self.ten_bi_an,
                "size": self.size, "n_sources": self.n_sources,
                "sources": [{"source": s, "n": n} for s, n in sorted(self.sources.items(), key=lambda x: (-x[1], x[0]))],
                "first_seen": self.first_seen, "last_seen": self.last_seen, "medoid_title": self.medoid_title,
                "tong_diem": self.tong_diem, "diem_cao_nhat": self.diem_cao_nhat, "luc_cao_nhat": self.luc_cao_nhat,
                "so_gio_trong_top10": self.so_gio_trong_top10}


class EventStore:
    """Một lần chạy pipeline trong RAM. Mọi tên trả ra đi qua `Event.ten` (đã áp cửa sổ ẩn tên lúc nạp)."""

    def __init__(self, run_dir: str | Path, hide_window: tuple[datetime, datetime] | None):
        t0 = time.perf_counter()
        self.run_dir = Path(run_dir)
        for f in ("manifest.json", "su_kien.csv", "bai_su_kien.csv"):
            if not (self.run_dir / f).is_file():
                raise RunNotFound(f"{rel_label(self.run_dir)} thiếu {f}. {NO_RUN_MESSAGE}")
        self.manifest: dict = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.run_id: str = self.manifest.get("run_id") or self.run_dir.name
        self.hide_window = hide_window
        if hide_window is None:
            log.warning("run %s: KHÔNG ẩn tên (cửa sổ tắt)", self.run_id)
        rows = _read_csv(self.run_dir / "su_kien.csv")
        in_win = {r["event_id"] for r in rows if self._in_window(r)}
        near = self._near_duplicates(rows, in_win)
        self.n_hidden_window, self.n_hidden_near = len(in_win), len(near)
        self.events: dict[str, Event] = {}
        for r in rows:
            self.events[r["event_id"]] = self._event(r, r["event_id"] in in_win or r["event_id"] in near)
        del rows                                       # tên mô hình gốc không sống quá hàm nạp
        # bài của từng sự kiện, sắp theo thời gian
        self.articles: dict[str, list[dict[str, Any]]] = {}
        all_ts: list[float] = []
        for r in _read_csv(self.run_dir / "bai_su_kien.csv"):
            ts = datetime.fromisoformat(r["published_at"]).timestamp()
            all_ts.append(ts)
            self.articles.setdefault(r["event_id"], []).append(
                {"article_id": r["article_id"], "published_at": r["published_at"], "ts": ts, "source": r["source"],
                 "category": r.get("category") or None, "title": r.get("title", ""), "is_medoid": r.get("is_medoid") == "1"})
        for xs in self.articles.values():
            xs.sort(key=lambda a: a["ts"])

        # tham số + lưới mốc + mức nền của bước trend
        self.cfg = {**trending.DEFAULTS, **(self.manifest.get("config", {}).get("trending") or {})}
        st = self.manifest.get("steps", {}).get("trend", {})
        start = datetime.fromisoformat(st["start"]) if st.get("start") else trending.day(self.cfg["start"])
        end = datetime.fromisoformat(st["end"]) if st.get("end") else trending.day(self.cfg["end"])
        self.step_s = float(self.cfg["step_hours"]) * 3600
        self.grid0 = start.timestamp()                                   # mốc t_k = grid0 + k·step, k ≥ 1
        self.n_steps = len(trending.steps(start, end, self.cfg["step_hours"]))
        self.baseline = trending.hourly_baseline(all_ts, trending.day(self.cfg["baseline_start"]),
                                                 trending.day(self.cfg["baseline_end"]))
        ref = st.get("baseline_hour")
        if ref and max(abs(a - b) for a, b in zip(ref, self.baseline)) > 1e-3:
            log.warning("mức nền tính lại lệch manifest.steps.trend.baseline_hour — chuỗi điểm có thể lệch xu_huong.csv")

        # bảng xu hướng top-K mỗi giờ
        self.trend: dict[int, list[dict[str, Any]]] = {}
        self.rank: dict[tuple[str, int], int] = {}
        path = self.run_dir / "xu_huong.csv"
        for r in (_read_csv(path) if path.is_file() else []):
            k = self._k(datetime.fromisoformat(r["t"]).timestamp())
            row = {"hang": int(r["hang"]), "event_id": r["event_id"], "score": float(r["score"]),
                   "so_bai_den_t": int(r["so_bai_den_t"]), "so_bai_3h": int(r["so_bai_3h"]), "so_bao": int(r["so_bao"]),
                   "n_nguon_hd": float(r["n_nguon_hd"]), "van_toc": float(r["van_toc"]),
                   "tuoi_gio": float(r["tuoi_gio"])}
            self.trend.setdefault(k, []).append(row)
            self.rank[(r["event_id"], k)] = row["hang"]
        for rows in self.trend.values():
            rows.sort(key=lambda x: x["hang"])
        need = int(self.manifest.get("config", {}).get("export", {}).get("latest_min_candidates", 10))
        full = [k for k, rows in self.trend.items() if len(rows) >= need]
        self.default_k = max(full) if full else (max(self.trend) if self.trend else self.n_steps)
        self.sources = sorted({s for e in self.events.values() for s in e.sources})
        self.n_articles = len(all_ts)
        self.data_from = _iso(min(all_ts)) if all_ts else None
        self.data_to = _iso(max(all_ts)) if all_ts else None
        self.loaded_at = datetime.now().astimezone()
        self.load_seconds = round(time.perf_counter() - t0, 2)

    # ------------------------------------------------------------------ nạp
    @classmethod
    def from_env(cls) -> EventStore:
        """EVENTS_RUN_DIR (hoặc run đầy đủ mới nhất trong data/runs/) + EVENTS_HIDE_NAMES_WINDOW (xem parse_hide_window)."""
        raw = os.environ.get("EVENTS_RUN_DIR", "").strip()
        if raw:
            run_dir = Path(raw) if Path(raw).is_absolute() else ROOT / raw
            if not run_dir.is_dir():
                raise RunNotFound(f"EVENTS_RUN_DIR={rel_label(run_dir)} không tồn tại. {NO_RUN_MESSAGE}")
        else:
            run_dir = find_run_dir()
            if run_dir is None:
                raise RunNotFound(NO_RUN_MESSAGE)
        return cls(run_dir, parse_hide_window(os.environ.get("EVENTS_HIDE_NAMES_WINDOW")))

    def _near_duplicates(self, rows: list[dict[str, str]], in_win: set[str]) -> set[str]:
        """event_id NGOÀI cửa sổ có tên mô hình Jaccard âm tiết ≥ NEAR_DUP_JACCARD với một tên bí mật (gồm trùng hẳn)."""
        if not in_win:
            return set()
        secret = {r["ten"] for r in rows if r["event_id"] in in_win and r["nguon"] == "model"}
        path = self.run_dir / "ten_su_kien.csv"
        if path.is_file():                                     # tên mô hình bị loại (rơi về medoid) cũng là bí mật
            secret |= {r["ten_mo_hinh"] for r in _read_csv(path) if r["event_id"] in in_win and r.get("ten_mo_hinh")}
        sec = [x for x in (syllables(s) for s in secret) if x]
        index: dict[str, list[int]] = {}                       # âm tiết → các tên bí mật chứa nó
        for i, x in enumerate(sec):
            for w in x:
                index.setdefault(w, []).append(i)
        out = set()
        for r in rows:
            if r["event_id"] in in_win or r["nguon"] != "model":
                continue
            v = syllables(r["ten"])
            common = Counter(i for w in v for i in index.get(w, ()))
            if any(c / (len(v) + len(sec[i]) - c) >= NEAR_DUP_JACCARD - 1e-12 for i, c in common.items()):
                out.add(r["event_id"])
        return out

    def _in_window(self, r: dict[str, str]) -> bool:
        if not self.hide_window:
            return False
        lo, hi = self.hide_window
        return datetime.fromisoformat(r["first_seen"]) < hi and datetime.fromisoformat(r["last_seen"]) >= lo

    def _event(self, r: dict[str, str], hidden: bool) -> Event:
        first, last = datetime.fromisoformat(r["first_seen"]), datetime.fromisoformat(r["last_seen"])
        medoid = r.get("medoid_title") or ""
        # Bị ẩn: KHÔNG giữ r["ten"] ở đâu cả — chỉ tiêu đề bài medoid (văn bản báo, không phải đầu ra mô hình).
        ten = (medoid or "(tên đang ẩn)") if hidden else r["ten"]
        sources: dict[str, int] = {}
        for part in (r.get("sources") or "").split():
            s, _, n = part.rpartition(":")
            sources[s] = int(n)
        return Event(event_id=r["event_id"], ten=ten, nguon_ten="an" if hidden else r["nguon"], ten_bi_an=hidden,
                     size=int(r["size"]), n_sources=int(r["n_sources"]), sources=sources,
                     first_seen=r["first_seen"], last_seen=r["last_seen"], first_ts=first.timestamp(),
                     last_ts=last.timestamp(), medoid_title=medoid, tong_diem=_f(r.get("tong_diem", "")),
                     diem_cao_nhat=_f(r.get("diem_cao_nhat", "")), luc_cao_nhat=r.get("luc_cao_nhat") or None,
                     so_gio_trong_top10=int(r.get("so_gio_trong_top10") or 0), key=fold(f"{ten} {medoid}"))

    # ------------------------------------------------------------------ lưới mốc
    def _k(self, ts: float) -> int:
        """Chỉ số mốc (làm tròn xuống) của thời điểm ts: t_k = grid0 + k·step."""
        return math.floor((ts - self.grid0) / self.step_s + 1e-9)

    def _t(self, k: int) -> datetime:
        return datetime.fromtimestamp(self.grid0 + k * self.step_s, VN)

    def parse_t(self, value: str) -> int:
        """Chuỗi ISO (không múi giờ = giờ VN) → chỉ số mốc, làm tròn xuống theo lưới. Ngoài khoảng → ValueError."""
        dt = datetime.fromisoformat(value)
        dt = dt.replace(tzinfo=VN) if dt.tzinfo is None else dt
        k = self._k(dt.timestamp())
        if not 1 <= k <= self.n_steps:
            raise ValueError(f"t ngoài khoảng có dữ liệu ({self._t(1).isoformat()} → {self._t(self.n_steps).isoformat()})")
        return k

    # ------------------------------------------------------------------ truy vấn
    def run_info(self) -> dict[str, Any]:
        n_hidden = sum(e.ten_bi_an for e in self.events.values())
        notes = ["Điểm xu hướng CHƯA được đánh giá (chưa có nhãn 'Xem nhiều'); tham số chọn tạm.",
                 "Tên sự kiện do mô hình sinh, chưa người duyệt (kiểm tra độc lập ước ~12% tên mô hình sai nghĩa).",
                 "Cụm gom trên toàn kho: xem lại một giờ trong quá khứ vẫn dùng cụm/tên tính bằng cả bài sau giờ đó."]
        win = None
        if self.hide_window:
            lo, hi = self.hide_window
            win = {"tu_ngay": lo.date().isoformat(), "den_ngay": (hi - timedelta(days=1)).date().isoformat()}
            notes.append(f"Tên của {n_hidden} sự kiện đang ẩn ({self.n_hidden_window} giao {win['tu_ngay']} → "
                         f"{win['den_ngay']}, {self.n_hidden_near} ngoài khoảng có tên mô hình gần trùng) — hiển thị "
                         "tiêu đề bài đại diện — để giữ mù cho tập test đặt tên.")
        return {"run_id": self.run_id, "versions": self.manifest.get("versions", {}),
                "loaded_at": self.loaded_at, "load_seconds": self.load_seconds,
                "n_su_kien": len(self.events), "n_su_kien_nhieu_bai": sum(e.size >= 2 for e in self.events.values()),
                "n_bai": self.n_articles, "nguon_bao": self.sources,
                "du_lieu_tu": self.data_from, "du_lieu_den": self.data_to,
                "pham_vi_tu": (self.manifest.get("range") or {}).get("start"),
                "pham_vi_den": (self.manifest.get("range") or {}).get("end"),
                "xu_huong_tu": self._t(1).isoformat(), "xu_huong_den": self._t(self.n_steps).isoformat(),
                "cua_so_an_ten": win, "n_su_kien_bi_an": n_hidden, "ghi_chu": notes}

    def trend_times(self) -> dict[str, Any]:
        return {"dau": self._t(1).isoformat(), "cuoi": self._t(self.n_steps).isoformat(),
                "buoc_gio": float(self.cfg["step_hours"]), "so_moc": self.n_steps,
                "mac_dinh": self._t(self.default_k).isoformat(),
                "so_su_kien": [len(self.trend.get(k, ())) for k in range(1, self.n_steps + 1)]}

    def trending(self, k: int | None = None) -> dict[str, Any]:
        k = self.default_k if k is None else k
        items = []
        for r in self.trend.get(k, []):
            e = self.events.get(r["event_id"])
            if e is None:
                continue
            items.append({**r, "ten": e.ten, "nguon_ten": e.nguon_ten, "ten_bi_an": e.ten_bi_an})
        return {"t": self._t(k).isoformat(), "t_truoc": self._t(k - 1).isoformat() if k > 1 else None,
                "t_sau": self._t(k + 1).isoformat() if k < self.n_steps else None,
                "mac_dinh": self._t(self.default_k).isoformat(), "items": items}

    def list_events(self, q: str | None = None, source: str | None = None, date_from: str | None = None,
                    date_to: str | None = None, min_size: int = 2, sort: str = "hot", page: int = 1,
                    page_size: int = 20) -> dict[str, Any]:
        if sort not in SORTS:
            raise ValueError(f"sort không hợp lệ: {sort} (chọn {', '.join(SORTS)})")
        lo = trending.day(date_from).timestamp() if date_from else None
        hi = (trending.day(date_to) + timedelta(days=1)).timestamp() if date_to else None
        needle = fold(q) if q else ""
        src = (source or "").strip().lower()
        hits = [e for e in self.events.values()
                if e.size >= min_size and (not src or src in e.sources) and (not needle or needle in e.key)
                and (lo is None or e.last_ts >= lo) and (hi is None or e.first_ts < hi)]
        key: Callable[[Event], tuple] = {
            "hot": lambda e: (-(e.tong_diem or 0.0), -e.size, -e.last_ts, e.event_id),
            "newest": lambda e: (-e.last_ts, -e.size, e.event_id),
            "size": lambda e: (-e.size, -(e.tong_diem or 0.0), -e.last_ts, e.event_id)}[sort]
        hits.sort(key=key)
        page_size = max(1, min(page_size, 100))
        page = max(1, page)
        return {"total": len(hits), "page": page, "page_size": page_size,
                "items": [e.summary() for e in hits[(page - 1) * page_size: page * page_size]]}

    def series(self, event_id: str) -> tuple[list[dict[str, Any]], bool]:
        """Số bài theo giờ + điểm xu hướng tính lại (score_at) trên lưới mốc của run, từ trước bài đầu tới khi hết
        bài trong cửa sổ W. → (điểm, bị cắt bớt?)."""
        arts = self.articles.get(event_id, [])
        if not arts:
            return [], False
        idx = trending.EventIndex([{"event_id": event_id, "ts": a["ts"], "source": a["source"], "title": a["title"]}
                                   for a in arts])
        win_s = float(self.cfg["window_hours"]) * 3600
        k0 = math.ceil((arts[0]["ts"] - self.grid0) / self.step_s - 1e-9) - 1     # một mốc trước bài đầu
        k1 = math.ceil((arts[-1]["ts"] + win_s - self.grid0) / self.step_s - 1e-9) + 1
        cut = k1 - k0 + 1 > MAX_SERIES_POINTS
        k1 = min(k1, k0 + MAX_SERIES_POINTS - 1)
        ts_all = [a["ts"] for a in arts]
        out = []
        for k in range(k0, k1 + 1):
            t = self._t(k)
            tt = t.timestamp()
            n = bisect_right(ts_all, tt)
            rows = trending.score_at(idx, t, self.cfg, self.baseline)      # chỉ chứa e → 0 hoặc 1 dòng
            out.append({"t": t.isoformat(), "so_bai": n - bisect_right(ts_all, tt - self.step_s), "so_bai_den_t": n,
                        "diem": round(rows[0]["score"], 6) if rows else 0.0, "ung_vien": bool(rows),
                        "hang": self.rank.get((event_id, k))})
        return out, cut

    def get_event(self, event_id: str,
                  urls: Callable[[list[str]], dict[str, str]] | None = None) -> dict[str, Any] | None:
        e = self.events.get(event_id)
        if e is None:
            return None
        arts = self.articles.get(event_id, [])
        url_of: dict[str, str] = {}
        if urls and arts:
            try:
                url_of = urls([a["article_id"] for a in arts])
            except Exception:                    # thiếu URL không được làm hỏng trang sự kiện
                log.exception("không lấy được URL bài từ Silver")
        series, cut = self.series(event_id)
        by_cat = Counter(a["category"] for a in arts if a["category"])
        return {**e.summary(),
                "chuyen_muc": [{"category": c, "n": n} for c, n in by_cat.most_common()],
                "bai": [{"article_id": a["article_id"], "title": a["title"], "source": a["source"],
                         "category": a["category"], "published_at": a["published_at"], "is_medoid": a["is_medoid"],
                         "url": url_of.get(a["article_id"])} for a in arts],
                "chuoi": series, "chuoi_bi_cat": cut}
