"""Nhãn yếu 4 mức "mức độ liên quan giữa hai bài" (v4) để fine-tune embedding bằng CoSENT / AnglE.

    uv run --group embed python -m eventrank.weak_labels.graded sample     # xuất mẫu cho Claude gán mù
    uv run --group embed python -m eventrank.weak_labels.graded split --name test   # chia thành phần 50 cặp
    uv run --group embed python -m eventrank.weak_labels.graded merge --name test   # ghép parts/*_labeled.csv
    uv run --group embed python -m eventrank.weak_labels.graded build      # gộp luật + nhãn Claude → file train
    uv run --group embed python -m eventrank.weak_labels.graded evaluate   # đo luật trên tập đo (holdout)
    uv run --group embed python -m eventrank.weak_labels.graded human      # 100 cặp cho người gán tay
    uv run --group embed python -m eventrank.weak_labels.graded agree      # κ người ↔ Claude

Thang điểm (định nghĩa Gói 1 / phương án E, docs/tong-hop.md mục 4):
    3 → 1,0  cùng sự kiện tin tức (B)
    2 → 0,6  cùng câu chuyện, khác sự kiện (C) — ví dụ điện đàm Trump–Putin ↔ đặc phái viên Mỹ tới Kyiv
    1 → 0,3  cùng chủ đề / cùng khuôn tin, khác đối tượng — giá vàng hai ngày, điểm chuẩn hai trường
    0 → 0,0  không liên quan
CoSENT chỉ dùng THỨ TỰ giữa các cặp, nên giá trị 0,6 / 0,3 không cần chính xác; chỉ cần 3 > 2 > 1 > 0.

Nguồn nhãn: tái dùng toàn bộ cặp ứng viên + đặc trưng của v3 (`data/weak_labels/v3/pairs.jsonl`, không chạy lại
embedding). Luật gán phần chắc chắn (mức 3, mức 1 kiểu khuôn tin, mức 0); phần còn lại là VÙNG XÁM, Claude gán
mù theo `docs/huong-dan-gan-4-muc.md`. Mức 2 chỉ đến từ Claude: luật "chung thực thể nổi bật nhưng p thấp" lẫn
quá nhiều loại (chung sản phẩm, chung hội nghị, bài tổng hợp, cặp cùng sự kiện bị bỏ sót).

Ba tập Claude gán, không chồng nhau:
    tune  (split train)   chỉnh luật — được nhìn bao nhiêu cũng được
    test  (split holdout) chỉ để đo, có trọng số theo tầng; KHÔNG chỉnh luật trên tập này
    pool  (split train, vùng xám) nhãn đưa thẳng vào dữ liệu train
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

LEVEL_SCORE = {3: 1.0, 2: 0.6, 1: 0.3, 0: 0.0}
GREY = -1          # luật không chắc → Claude gán
EXCLUDED = -2      # bài tổng hợp nhiều tin: loại khỏi dữ liệu (Gói 1: loại khỏi gom cụm)

# Ngưỡng ban đầu (từ quan sát mẫu v3, CHƯA đo bằng nhãn 4 mức) — đo lại trên tập tune trước khi dùng thật
POS_P = 0.80              # = ngưỡng cặp dương của v3 (precision 0,93 trên tập đo v2)
SERIES_MIN_COS_HEAD = 0.15
TEMPLATE_MIN_COS_HEAD = 0.30     # chỉ dùng để chia tầng g_template, KHÔNG để gán nhãn (xem template_mask)
TEMPLATE_MAX_P = 0.50
NEG_MAX_P = 0.10
NEG_CONTENT_COS = 0.15    # = content_negative của v3: negative sai 2–3% (290 cặp có nhãn Claude)
NEG_CONTENT_WJACC = 0.10
NEG_MAX_DENSE = 0.55
CONFLICTS = ("conflict_doc", "conflict_org", "conflict_per", "conflict_event", "conflict_loc")

_ROUNDUP = re.compile(
    r"^\s*(tin tức (thế giới|sáng|trưa|chiều|tối|trong ngày|nổi bật|thể thao)"
    r"|điểm tin|bản tin|thời sự 24h|tin nóng|tin tức \d"
    r"|(kết quả|lịch thi đấu|lịch phát sóng|nhận định)( bóng đá)? hôm nay"
    r"|lịch thi đấu bóng đá|kết quả bóng đá)", re.IGNORECASE)


def is_roundup(title: str) -> bool:
    """Bài tổng hợp nhiều tin ("Tin tức thế giới 13-9: …", "Kết quả bóng đá hôm nay 13/9")."""
    return bool(_ROUNDUP.search(title))


def title_of(text: str) -> str:
    """`text` của articles.jsonl = tiêu đề + ". " + sapo."""
    return text.split(". ", 1)[0]


def template_mask(f: dict[str, np.ndarray]) -> np.ndarray:
    """Cùng khuôn tiêu đề, mỗi bài có thực thể chính mà bài kia không nhắc ("Điểm chuẩn ĐH A" ↔ "… ĐH B").

    KHÔNG dùng để gán mức 1. Đo trên tập tune v4 (24 cặp, Claude gán mù): mức 1 chỉ 62%, mức 3 tới 21% — các
    hoạt động của cùng một chuyến thăm ("hội kiến Medvedev" ↔ "hội kiến Matvienko", "lên đường" ↔ "đã đến
    Seoul") cũng có khuôn tiêu đề giống nhau và khác thực thể. Siết thêm ent_wjacc / cos_lead chỉ bớt 2/5 lỗi.
    Gán 0,3 cho cặp cùng sự kiện là dạy mô hình đẩy chúng ra xa → để Claude gán (tầng g_template).
    """
    conflict = np.zeros(len(f["p"]), bool)
    for c in CONFLICTS:
        conflict |= f[c] > 0
    return ((f["p"] < TEMPLATE_MAX_P) & conflict & (f["cos_head"] >= TEMPLATE_MIN_COS_HEAD)
            & (f["n_head_shared"] == 0) & (f["same_category"] > 0))


def rule_levels(f: dict[str, np.ndarray], titles_a: list[str], titles_b: list[str]) -> np.ndarray:
    """Mức do luật gán cho từng cặp: 3 / 1 / 0, GREY nếu không chắc, EXCLUDED nếu có bài tổng hợp.

    `f` là đặc trưng cặp của v3 (pairs.FEATURES) kèm cột `p` (xác suất cùng sự kiện đã hiệu chỉnh).
    Đo trên tập tune v4 (Claude gán mù, 25 cặp mỗi tầng): mức 3 đúng 0,96 · chuỗi định kỳ (mức 1) đúng 0,92 ·
    mức 0 đúng 0,83 (phần sai còn lại là mức 1, cùng lĩnh vực — nhầm 0↔1 ít hại khi train).
    """
    p = f["p"]
    lv = np.full(len(p), GREY, dtype=int)
    dense = np.nan_to_num(f["cos_dense"], nan=-1.0)

    unrelated = ((p < NEG_MAX_P) & (f["cos_lead"] < NEG_CONTENT_COS) & (f["ent_wjacc"] < NEG_CONTENT_WJACC)
                 & (dense < NEG_MAX_DENSE))
    series = (f["date_conflict"] > 0) & (f["same_category"] > 0) & (f["cos_head"] >= SERIES_MIN_COS_HEAD)
    lv[unrelated] = 0
    lv[series] = 1
    lv[p >= POS_P] = 3
    roundup = np.array([is_roundup(a) or is_roundup(b) for a, b in zip(titles_a, titles_b)], bool)
    lv[roundup] = EXCLUDED
    return lv


def bucket_of(level: int, f_row: dict[str, float]) -> str:
    """Tầng lấy mẫu: luật đã gán thì theo mức; vùng xám chia theo loại bằng chứng."""
    if level == 3:
        return "r3"
    if level == 1:
        return "r1_series"
    if level == 0:
        return "r0"
    if f_row.get("template"):
        return "g_template"         # cùng khuôn tin: mức 1 hoặc cùng chuyến thăm (mức 3) — Claude phân định
    if f_row["n_head_shared"] >= 1:
        return "g_story"            # chung thực thể nổi bật ở tiêu đề/sapo: hay là cùng câu chuyện
    if f_row["p"] >= 0.1:
        return "g_mid"
    return "g_low"


def parse_level(s: str) -> int | None:
    s = (s or "").strip().lower()
    if s == "x":
        return EXCLUDED
    if s in ("0", "1", "2", "3"):
        return int(s)
    return None


HARD_MAX_COS_HEAD = 0.20
HARD_MAX_DT = 48
HARD_DENSE = 0.60
HARD_DENSE_HIGH = 0.70      # nhóm ưu tiên khi lấy mẫu
HARD_WJACC = 0.20


def hard_mask(f: dict[str, np.ndarray]) -> np.ndarray:
    """Cặp "có thể cùng nội dung nhưng khác chữ": cần Claude gán để dạy mô hình tầng trùng từ vựng thấp.

    Train v4 (14/10/2026): chỉ 11% trong 7.673 cặp mức 3 có cos_head < 0,2 → mô hình fine-tune (CoSENT, 3 seed)
    không tăng recall ở tầng khác chữ (0,51 → 0,46). Trong vùng này, 649 cặp Claude đã gán: 26% mức 3, 16% mức 2.
    Tín hiệu cùng nội dung đến từ MiniLM (khác họ với mô hình fine-tune) hoặc NER — không dùng chính mô hình
    đang train để tránh vòng lặp.
    """
    dense = np.nan_to_num(f["cos_dense"], nan=-1.0)
    signal = (dense >= HARD_DENSE) | (f["ent_wjacc"] >= HARD_WJACC) | (f["n_head_shared"] >= 1)
    return ((f["cos_head"] < HARD_MAX_COS_HEAD) & (f["dt_hours"] <= HARD_MAX_DT) & (f["cross_source"] > 0)
            & (f["p"] < POS_P) & signal)


_LEAD_DATE = re.compile(r"(?<![\d.,/-])(\d{1,2})[./-](\d{1,2})(?:[./-]\d{2,4})?(?![\d/-])")
_QUOTED = re.compile(r"[\"“'‘]([^\"”'’]{6,60})[\"”'’]")
RECHECK_MIN_DT = 30


def lead_date(text: str) -> tuple[int, int] | None:
    """Ngày/tháng đầu tiên trong 120 ký tự đầu của sapo ("Tối 18/7, …", "hôm nay 6-9") — ngày diễn ra việc được kể."""
    sapo = text.split(". ", 1)[1] if ". " in text else ""
    for m in _LEAD_DATE.finditer(sapo[:120]):
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return d, mo
    return None


def needs_recheck(level: int, text_a: str, text_b: str, f_row: dict[str, float]) -> bool:
    """Cặp đã có nhãn cần Claude xem lại theo quy tắc 29/10/2026 (mỗi trận / mỗi hoạt động là một sự kiện).

    Rà tay 29/10 tìm thấy mức 3 sai cho hai trận khác nhau (U20 VN–Iran 6/9 ↔ –Palestine 3/9; Cantho Catfish 18/7 ↔
    16/7), hai người ở hai nước (Trần Thanh Mẫn ở Hàn Quốc ↔ Tô Lâm ở Nga), hai cuộc gặp của cùng chuyến (quy tắc cũ
    13/10); và mức 0 sai cho hai bài cùng đêm diễn "Tổ quốc trong tim". Quét train: 1.872/8.066 cặp mức 3 có ít nhất
    một dấu hiệu dưới (nhiều cặp vẫn đúng — ví dụ nhiều báo đưa cùng một cuộc gặp cách nhau > 30h — nên phải gán lại,
    không tự sửa).
    """
    if level == 3:
        da, db = lead_date(text_a), lead_date(text_b)
        return bool((da and db and da != db) or f_row.get("conflict_per") or f_row.get("conflict_loc")
                    or (f_row.get("dt_hours") or 0) >= RECHECK_MIN_DT)
    if level == 0:
        qa = {q.strip().lower() for q in _QUOTED.findall(title_of(text_a))}
        qb = {q.strip().lower() for q in _QUOTED.findall(title_of(text_b))}
        return bool(qa & qb)
    return False


def needs_relabel(level: int, bucket: str) -> bool:
    """Cặp pool cần Claude gán lại theo hướng dẫn đã bổ sung (13/10/2026).

    Người duyệt 100 cặp tập test: 5/6 lần sửa là NÂNG mức, chủ yếu 2→3 (cùng chuyến đi, cùng đợt tập trung) →
    gán lại mọi cặp mức 2, và mức 1 ở vùng chung thực thể nổi bật / cùng khuôn tin, nơi lỗi này tập trung.
    """
    return level == 2 or (level == 1 and bucket in ("g_story", "g_template"))


def transitivity_conflicts(levels: dict[frozenset, int]) -> set[frozenset]:
    """Cạnh nằm trong tam giác mâu thuẫn bắc cầu: A–B = 3, A–X = 3 mà B–X < 3 (cùng sự kiện phải bắc cầu).

    Đo trên train v4 sau recheck 29/10: 431 lượt "3–3–2" (62 trước recheck) — các cạnh cùng ngày của cùng chuyến thăm
    không bị needs_recheck chọn nên vẫn mang mức 3 theo quy tắc cũ, trong khi cạnh bên cạnh đã hạ xuống 2.
    """
    adj: dict[str, set[str]] = defaultdict(set)
    for e in levels:
        a, b = tuple(e)
        adj[a].add(b)
        adj[b].add(a)
    bad: set[frozenset] = set()
    for e, lv in levels.items():
        if lv != 3:
            continue
        a, b = tuple(e)
        for x in adj[a] & adj[b]:
            ax, bx = frozenset((a, x)), frozenset((b, x))
            for three, low in ((ax, bx), (bx, ax)):
                if levels[three] == 3 and levels[low] < 3:
                    bad |= {e, three, low}
    return bad


def conflict_groups(levels: dict[frozenset, int], conflicts: set[frozenset]) -> list[list[frozenset]]:
    """Nhóm bài liên thông qua các cạnh mâu thuẫn; mỗi nhóm trả về MỌI cạnh đã gán giữa hai bài cùng nhóm, để gán lại
    cả nhóm một lượt và giữ bắc cầu."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in conflicts:
        a, b = tuple(e)
        parent[find(a)] = find(b)
    groups: dict[str, list[frozenset]] = defaultdict(list)
    for e in levels:
        a, b = tuple(e)
        if a in parent and b in parent and find(a) == find(b):
            groups[find(a)].append(e)
    return list(groups.values())


def weighted_level_shares(rows: dict[str, list[int]], sizes: dict[str, int]) -> dict[int, float]:
    """Tỉ lệ từng mức trong TỔNG THỂ từ mẫu phân tầng: mỗi cặp mẫu nặng N_tầng / n_tầng (Horvitz–Thompson)."""
    tot: dict[int, float] = defaultdict(float)
    for s, levels in rows.items():
        if not levels:
            continue
        w = sizes.get(s, 0) / len(levels)
        for lv in levels:
            tot[lv] += w
    z = sum(tot.values())
    return {k: v / z for k, v in tot.items()} if z else {}


def kappa(a: list[int], b: list[int], levels: tuple[int, ...] = (0, 1, 2, 3), weights: str = "none") -> float:
    """Cohen's κ nhiều mức. weights="quadratic": lệch càng xa phạt càng nặng (3↔0 nặng gấp 9 lần 3↔2)."""
    k = len(levels)
    pos = {v: i for i, v in enumerate(levels)}
    O = np.zeros((k, k))
    for x, y in zip(a, b):
        O[pos[x], pos[y]] += 1
    O /= O.sum()
    E = np.outer(O.sum(1), O.sum(0))
    i, j = np.indices((k, k))
    W = ((i - j) ** 2 / (k - 1) ** 2) if weights == "quadratic" else (i != j).astype(float)
    de = (W * E).sum()
    return 1.0 if de == 0 else float(1 - (W * O).sum() / de)


# ---------------------------------------------------------------------------------------------- dữ liệu v3

FEATS = ["p", "dt_hours", "cross_source", "same_category", "ent_wjacc", "n_head_shared", "cos_head",
         "cos_lead", "cos_dense", "date_conflict", *CONFLICTS]


def load_v3(v3: Path):
    arts = {}
    with open(v3 / "articles.jsonl", encoding="utf-8") as fh:
        for line in fh:
            a = json.loads(line)
            arts[a["article_id"]] = a
    cols: dict[str, list[float]] = {k: [] for k in FEATS}
    a_ids, b_ids, split = [], [], []
    with open(v3 / "pairs.jsonl", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            for k in FEATS:
                cols[k].append(np.nan if r[k] is None else float(r[k]))
            a_ids.append(r["a"])
            b_ids.append(r["b"])
            split.append(r["split"])
    f = {k: np.array(v) for k, v in cols.items()}
    return arts, f, a_ids, b_ids, np.array(split)


def _levels_buckets(arts, f, a_ids, b_ids):
    lv = rule_levels(f, [title_of(arts[a]["text"]) for a in a_ids], [title_of(arts[b]["text"]) for b in b_ids])
    tm = template_mask(f)
    buckets = np.array([bucket_of(int(lv[r]), {"date_conflict": f["date_conflict"][r], "template": bool(tm[r]),
                                                "n_head_shared": f["n_head_shared"][r], "p": f["p"][r]})
                        if lv[r] != EXCLUDED else "excluded" for r in range(len(lv))])
    return lv, buckets


def load_bodies(ids: set[str], silver_glob: str, n_chars: int) -> dict[str, str]:
    """n_chars ký tự đầu thân bài (Silver `content_text`) — chỗ thường có ai / ở đâu / ngày nào.

    Đo trên 100 cặp tập test (Claude đọc toàn văn): thân bài quyết định nhãn ở 12/100 cặp, đều nhờ chi tiết ở
    các đoạn đầu (cùng đoàn, cùng buổi, khác dự án).
    """
    import glob

    out = {}
    for fn in sorted(glob.glob(silver_glob)):
        with open(fn, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("article_id") in ids:
                    body = " ".join((r.get("content_text") or "").split())
                    out[r["article_id"]] = body[:n_chars] + (" …" if len(body) > n_chars else "")
    return out


def _write_blind(path: Path, rows: list[tuple[int, str]], arts, a_ids, b_ids, f, seed: int,
                 bodies: dict[str, str] | None = None, shuffle: bool = True) -> None:
    """CSV gán mù: chỉ văn bản, báo, ngày đăng (và đoạn đầu thân bài nếu có). Không có p, mức luật, tầng."""
    if shuffle:
        rng = np.random.default_rng(seed)
        rows = [rows[k] for k in rng.permutation(len(rows))]
    with open(path, "w", encoding="utf-8", newline="") as fh, \
            open(path.with_name(path.stem + "_ids.csv"), "w", encoding="utf-8", newline="") as gh:
        w, wi = csv.writer(fh), csv.writer(gh)
        w.writerow(["pair_no", "source_a", "date_a", "text_a", "source_b", "date_b", "text_b"]
                   + (["body_a", "body_b"] if bodies is not None else []) + ["level", "confidence", "reason"])
        wi.writerow(["pair_no", "a", "b", "bucket", "rule_level", "p"])
        for k, (r, b) in enumerate(rows):
            A, B = arts[a_ids[r]], arts[b_ids[r]]
            extra = [bodies.get(a_ids[r], ""), bodies.get(b_ids[r], "")] if bodies is not None else []
            w.writerow([k, A["source"], A["published_at"][:16], A["text"], B["source"], B["published_at"][:16],
                        B["text"], *extra, "", "", ""])
            wi.writerow([k, a_ids[r], b_ids[r], b, "", round(float(f["p"][r]), 4)])


def cmd_sample(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    arts, f, a_ids, b_ids, split = load_v3(Path(args.v3))
    lv, buckets = _levels_buckets(arts, f, a_ids, b_ids)
    print("mức luật:", dict(Counter(lv.tolist())))
    print("tầng:", dict(Counter(buckets.tolist())))
    rng = np.random.default_rng(args.seed)
    taken: set[int] = set()
    keep = [nm for nm in SETS if nm not in args.sets.split(",")]
    row_of = {(a, b): r for r, (a, b) in enumerate(zip(a_ids, b_ids))}
    for nm in keep:                          # tập đã gán giữ nguyên; tập sinh lại không được trùng với chúng
        ids = out / f"{nm}_ids.csv"
        if ids.exists():
            with open(ids, encoding="utf-8") as fh:
                taken.update(row_of[(r["a"], r["b"])] for r in csv.DictReader(fh))

    hm = hard_mask(f) & (lv != EXCLUDED)
    dense = np.nan_to_num(f["cos_dense"], nan=-1.0)
    hgroup = np.where(hm & (dense >= HARD_DENSE_HIGH), "h_dense", np.where(hm, "h_other", ""))

    def draw(sp: str, per_bucket: dict[str, int]) -> list[tuple[int, str]]:
        rows = []
        for b, n in per_bucket.items():
            grp = hgroup if b.startswith("h_") else buckets
            idx = [r for r in np.where((split == sp) & (grp == b))[0] if r not in taken]
            pick = rng.choice(idx, size=min(n, len(idx)), replace=False) if idx else []
            taken.update(int(r) for r in pick)
            # file id ghi TẦNG THƯỜNG của cặp (để tính trọng số); nhóm h_* ghi kèm sau dấu "+"
            rows += [(int(r), b if not b.startswith("h_") else f"{buckets[r]}+{b}") for r in pick]
        return rows

    all_b = ["r3", "r1_series", "r0", "g_template", "g_story", "g_mid", "g_low"]
    plan = {"tune": ("train", {b: args.tune_per_bucket for b in all_b}),
            "test": ("holdout", {b: args.test_per_bucket for b in all_b}),
            "pool": ("train", {"g_template": args.pool_template, "g_story": args.pool_story,
                               "g_mid": args.pool_mid, "g_low": args.pool_low}),
            # đợt 2 (13/10): thêm tập đo và dữ liệu train, ưu tiên vùng có mức 2–3
            "test2": ("holdout", {b: args.test2_per_bucket for b in all_b}),
            "pool2": ("train", {"g_template": args.pool2_template, "g_story": args.pool2_story,
                                "g_mid": args.pool2_mid, "g_low": args.pool2_low}),
            # đợt 3 (14/10): cặp cùng nội dung, khác chữ (hard_mask)
            "hard": ("train", {"h_dense": args.hard_dense, "h_other": args.hard_other}),
            "hardtest": ("holdout", {"h_dense": args.hardtest_dense, "h_other": args.hardtest_other})}
    for name in args.sets.split(","):
        sp, per = plan[name]
        rows = draw(sp, per)
        bodies = (load_bodies({x for r, _ in rows for x in (a_ids[r], b_ids[r])}, args.silver_glob, args.body_chars)
                  if args.body_chars else None)
        _write_blind(out / f"{name}.csv", rows, arts, a_ids, b_ids, f, args.seed, bodies)
        ids = out / f"{name}_ids.csv"           # ghi lại mức luật vào file id (file gán mù không có)
        with open(ids, encoding="utf-8") as fh:
            recs = list(csv.DictReader(fh))
        key = {(a_ids[r], b_ids[r]): int(lv[r]) for r, _ in rows}
        for rec in recs:
            rec["rule_level"] = key[(rec["a"], rec["b"])]
        with open(ids, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
            w.writeheader()
            w.writerows(recs)
        print(f"{name}: {len(rows)} cặp {dict(Counter(b for _, b in rows))} → {out / name}.csv")
    if "test" in args.sets.split(","):
        hold = Counter(buckets[split == "holdout"].tolist())
        (out / "test_strata_sizes.json").write_text(json.dumps(dict(hold), indent=2), encoding="utf-8")


SETS = ("tune", "test", "pool", "test2", "pool2", "hard", "hardtest")
TEST_SETS = ("test", "test2")          # tập đo chung (lấy mẫu theo tầng); hardtest đo riêng, không gộp
HELD_SETS = ("test", "test2", "hardtest")
# gán lại theo quy tắc 29/10; tập sau đè tập trước
RECHECK_SETS = ("recheck", "recheck2", "recheck3", "recheck4", "retest", "audit_train", "retrain")
TRAIN_SETS = ("tune", "pool", "pool2", "hard")


def cmd_relabel(args) -> None:
    """relabel.csv: cặp pool cần gán lại theo hướng dẫn mới (needs_relabel), gán mù kèm đoạn đầu thân bài."""
    out = Path(args.out)
    arts, f, a_ids, b_ids, _ = load_v3(Path(args.v3))
    row_of = {(a, b): r for r, (a, b) in enumerate(zip(a_ids, b_ids))}
    rows = [(row_of[(r["a"], r["b"])], r["bucket"]) for r in read_labels(out, "pool")
            if needs_relabel(r["level"], r["bucket"])]
    bodies = load_bodies({x for r, _ in rows for x in (a_ids[r], b_ids[r])}, args.silver_glob, args.body_chars)
    _write_blind(out / "relabel.csv", rows, arts, a_ids, b_ids, f, args.seed, bodies)
    print(f"relabel: {len(rows)} cặp {dict(Counter(b for _, b in rows))} → {out / 'relabel.csv'}")


def cmd_recheck(args) -> None:
    """recheck.csv: cặp đã gán (train: graded_pairs.jsonl; đo: test, test2, hardtest, kể cả nhãn người) mà
    needs_recheck chọn → Claude gán mù lại kèm đoạn đầu thân bài. Nhãn mới đè nhãn cũ (trừ nhãn người khi xuất)."""
    out = Path(args.out)
    arts, f, a_ids, b_ids, _ = load_v3(Path(args.v3))
    row_of = {frozenset((a, b)): r for r, (a, b) in enumerate(zip(a_ids, b_ids))}
    cand: dict[frozenset, tuple[int, str]] = {}
    with open(out / "graded_pairs.jsonl", encoding="utf-8") as fh:
        for line in fh:
            g = json.loads(line)
            cand[frozenset((g["a_id"], g["b_id"]))] = (int(g["level"]), f"train_{g['source']}")
    for k, r in labels_by_pair(out, HELD_SETS).items():
        if r["level"] in (0, 1, 2, 3):
            cand[frozenset(k)] = (r["level"], r["set"])
    hum = out / "human_label_100.csv"
    if hum.exists():
        with open(out / "human_label_100_ids.csv", encoding="utf-8") as fh:
            hid = {r["pair_no"]: r for r in csv.DictReader(fh)}
        with open(hum, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                lv = parse_level(r.get("level_human", ""))
                key = frozenset((hid[r["pair_no"]]["a"], hid[r["pair_no"]]["b"]))
                if lv in (0, 1, 2, 3):
                    cand[key] = (lv, "human")
    feats = ("conflict_per", "conflict_loc", "dt_hours")
    rows = []
    for key, (lv, origin) in cand.items():
        r = row_of.get(key)
        if r is None:
            continue
        a, b = a_ids[r], b_ids[r]
        if needs_recheck(lv, arts[a]["text"], arts[b]["text"], {k: f[k][r] for k in feats}):
            rows.append((r, f"{origin}|{lv}"))
    bodies = load_bodies({x for r, _ in rows for x in (a_ids[r], b_ids[r])}, args.silver_glob, args.body_chars)
    _write_blind(out / "recheck.csv", rows, arts, a_ids, b_ids, f, args.seed, bodies)
    print(f"recheck: {len(rows)} cặp {dict(Counter(b for _, b in rows))} → {out / 'recheck.csv'}")


def current_levels(out: Path) -> dict[frozenset, tuple[int, str]]:
    """Nhãn đang dùng của mọi cặp, cùng thứ tự ưu tiên như khi xuất: train = graded_pairs.jsonl (đã gồm recheck và nhãn
    ghi tay); tập đo = nhãn Claude → recheck → nhãn người → nhãn ghi tay. Cặp bị loại (x) không có mặt."""
    got: dict[frozenset, tuple[int, str]] = {}
    with open(out / "graded_pairs.jsonl", encoding="utf-8") as fh:
        for line in fh:
            g = json.loads(line)
            got[frozenset((g["a_id"], g["b_id"]))] = (int(g["level"]), f"train_{g['source']}")
    held = {frozenset(k): (r["level"], r["set"]) for k, r in labels_by_pair(out, HELD_SETS).items()}
    for k, r in labels_by_pair(out, RECHECK_SETS).items():
        if frozenset(k) in held:
            held[frozenset(k)] = (r["level"], held[frozenset(k)][1])
    hum = out / "human_label_100.csv"
    if hum.exists():
        with open(out / "human_label_100_ids.csv", encoding="utf-8") as fh:
            hid = {r["pair_no"]: r for r in csv.DictReader(fh)}
        with open(hum, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                lv = parse_level(r.get("level_human", ""))
                if lv is not None:
                    held[frozenset((hid[r["pair_no"]]["a"], hid[r["pair_no"]]["b"]))] = (lv, "human")
    for (a, b), lv in manual_overrides(out).items():
        if frozenset((a, b)) in held:
            held[frozenset((a, b))] = (lv, "manual")
    got |= held
    return {k: v for k, v in got.items() if v[0] in (0, 1, 2, 3)}


def reviewed_pairs(out: Path) -> set[frozenset]:
    """Cặp đã được gán lại theo quy tắc 29/10 (mọi tập RECHECK_SETS đã có) hoặc người dùng ghi tay."""
    done = {frozenset(k) for k in manual_overrides(out)}
    for nm in RECHECK_SETS:
        if (out / f"{nm}_ids.csv").exists():
            with open(out / f"{nm}_ids.csv", encoding="utf-8") as fh:
                done |= {frozenset((r["a"], r["b"])) for r in csv.DictReader(fh)}
    return done


def cmd_consistency(args) -> None:
    """<name>.csv: các nhóm cặp gán mù lại theo quy tắc 29/10, mỗi nhóm nằm liền nhau, không bị cắt giữa hai phần →
    parts/<name>_NN.csv (+ _articles.csv); Claude gán cả nhóm một lượt. --select:
      conflicts     mọi cạnh của các nhóm bài có mâu thuẫn bắc cầu (transitivity_conflicts) — recheck2…4
      held          mọi cặp mức 2–3 của tập đo (test, test2, hardtest, kể cả nhãn người) chưa được gán lại, gom theo
                    nhóm bài liên thông — retest
      train-sample  mẫu phân tầng --sample cặp train mức 2–3 chưa được gán lại (chia đều các tầng nguồn|mức) để đo tỉ
                    lệ nhãn cũ khác quy tắc mới — audit_train
      train-all     mọi cặp train mức 2–3 chưa được gán lại, gom theo nhóm bài liên thông (kèm mọi cạnh train giữa các
                    bài của nhóm) — retrain. Mẫu audit_train (180 cặp) cho thấy 12,5% [7,3–18,6%] nhãn cũ khác quy
                    tắc mới (mức 3 do Claude gán theo quy tắc 13/10: 33%)
    """
    out = Path(args.out)
    arts, f, a_ids, b_ids, _ = load_v3(Path(args.v3))
    row_of = {frozenset((a, b)): r for r, (a, b) in enumerate(zip(a_ids, b_ids))}
    cur = {k: v for k, v in current_levels(out).items() if k in row_of}
    levels = {k: v[0] for k, v in cur.items()}
    rng = np.random.default_rng(args.seed)
    if args.select == "conflicts":
        bad = transitivity_conflicts(levels)
        groups = conflict_groups(levels, bad)
    else:
        done = reviewed_pairs(out)
        todo = {e: v for e, v in cur.items() if v[0] in (2, 3) and e not in done}
        if args.select in ("held", "train-all"):
            want_train = args.select == "train-all"
            pool = {e: lv for e, lv in levels.items() if cur[e][1].startswith("train_") == want_train}
            bad = {e for e, (_, orig) in todo.items() if orig.startswith("train_") == want_train}
            groups = conflict_groups(pool, bad)
        else:
            strata: dict[str, list[frozenset]] = defaultdict(list)
            for e, (lv, orig) in sorted(todo.items(), key=lambda kv: sorted(kv[0])):
                if orig.startswith("train_"):
                    strata[f"{orig}|{lv}"].append(e)
            per = args.sample // len(strata)
            bad = {strata[s][k] for s in strata for k in rng.choice(len(strata[s]), min(per, len(strata[s])),
                                                                    replace=False)}
            groups = [[e] for e in bad]
            print("tầng (cỡ tổng thể):", {s: len(v) for s, v in strata.items()})
    groups = [sorted(groups[k], key=lambda e: min(arts[x]["published_at"] for x in e)) for k in rng.permutation(len(groups))]
    rows = [(row_of[e], f"{cur[e][1]}|{cur[e][0]}|g{g}") for g, grp in enumerate(groups) for e in grp]
    bodies = load_bodies({x for r, _ in rows for x in (a_ids[r], b_ids[r])}, args.silver_glob, args.body_chars)
    _write_blind(out / f"{args.name}.csv", rows, arts, a_ids, b_ids, f, args.seed, bodies, shuffle=False)
    # phần gán: bảng bài (mỗi bài một lần, kèm đoạn đầu thân bài) + bảng cặp trỏ tới mã bài — nhóm lớn (190 cặp,
    # ~25 bài) vẫn vừa một phiên; mỗi nhóm nằm trọn trong một phần
    (out / "parts").mkdir(exist_ok=True)
    parts: list[list[int]] = [[]]
    for g, grp in enumerate(groups):
        if parts[-1] and sum(len(groups[x]) for x in parts[-1]) + len(grp) > args.chunk:
            parts.append([])
        parts[-1].append(g)
    k0 = [0]
    for grp in groups:
        k0.append(k0[-1] + len(grp))
    for n, gs in enumerate(parts):
        art_no: dict[str, str] = {}
        pair_rows = []
        for g in gs:
            for i, e in enumerate(groups[g]):
                r = row_of[e]
                for x in (a_ids[r], b_ids[r]):
                    art_no.setdefault(x, f"g{g}_{sum(1 for v in art_no.values() if v.startswith(f'g{g}_')) + 1}")
                pair_rows.append([g, k0[g] + i, art_no[a_ids[r]], art_no[b_ids[r]], "", "", ""])
        base = out / "parts" / f"{args.name}_{n:02d}"
        with open(base.with_name(base.name + "_articles.csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["art", "source", "date", "text", "body"])
            w.writerows([no, arts[x]["source"], arts[x]["published_at"][:16], arts[x]["text"], bodies.get(x, "")]
                        for x, no in art_no.items())
        with open(base.with_suffix(".csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["group", "pair_no", "art_a", "art_b", "level", "confidence", "reason"])
            w.writerows(pair_rows)
    print(f"{args.name}: {len(bad)} cạnh chọn · {len(groups)} nhóm · {len(rows)} cặp "
          f"{dict(Counter(b.rsplit('|', 1)[0] for _, b in rows))} → {len(parts)} phần trong {out / 'parts'}/")


def manual_overrides(out: Path) -> dict[tuple[str, str], int]:
    """Nhãn người dùng quyết định trực tiếp (manual_overrides.csv) — ưu tiên cao nhất, khoá cả hai chiều."""
    path = out / "manual_overrides.csv"
    res: dict[tuple[str, str], int] = {}
    if path.exists():
        with open(path, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                lv = parse_level(r["level"])
                if lv is not None:
                    res[(r["a"], r["b"])] = res[(r["b"], r["a"])] = lv
    return res


def labels_by_pair(out: Path, names) -> dict[tuple[str, str], dict]:
    """Gộp nhãn nhiều tập theo (a, b); tập sau ghi đè tập trước (relabel đặt cuối để đè pool)."""
    got: dict[tuple[str, str], dict] = {}
    for nm in names:
        for r in read_labels(out, nm):
            got[(r["a"], r["b"])] = r | {"set": nm}
    return got


def read_labels(out: Path, name: str) -> list[dict]:
    """Ghép <name>_labeled.csv (pair_no, level, …) với <name>_ids.csv theo pair_no."""
    if not (out / f"{name}_ids.csv").exists():
        return []
    with open(out / f"{name}_ids.csv", encoding="utf-8") as fh:
        ids = {r["pair_no"]: r for r in csv.DictReader(fh)}
    lab = out / f"{name}_labeled.csv"
    if not lab.exists():
        return []
    rows = []
    with open(lab, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            lv = parse_level(r.get("level", ""))
            if lv is not None and r["pair_no"] in ids:
                rows.append(ids[r["pair_no"]] | {"level": lv, "reason": r.get("reason", "")})
    return rows


def cmd_evaluate(args) -> None:
    out = Path(args.out)
    for name in ("tune", "test"):
        rows = (list(labels_by_pair(out, TEST_SETS).values()) if name == "test" else read_labels(out, name))
        if not rows:
            print(f"[{name}] chưa có {name}_labeled.csv")
            continue
        print(f"\n[{name}] {len(rows)} cặp có nhãn Claude (không tính 'x')")
        by_b: dict[str, list[int]] = defaultdict(list)
        for r in rows:
            if r["level"] != EXCLUDED:
                by_b[r["bucket"]].append(r["level"])
        for b in sorted(by_b):
            c = Counter(by_b[b])
            n = len(by_b[b])
            print(f"  {b:12s} n={n:3d}  " + "  ".join(f"m{k}={c.get(k, 0) / n:.2f}" for k in (3, 2, 1, 0)))
        if name == "test":
            sizes = json.loads((out / "test_strata_sizes.json").read_text(encoding="utf-8"))
            grey = {b: v for b, v in by_b.items() if b.startswith("g_")}
            print("  tỉ lệ từng mức trong VÙNG XÁM holdout (có trọng số):",
                  {k: round(v, 3) for k, v in sorted(weighted_level_shares(grey, sizes).items())})
    hard = read_labels(out, "hardtest")
    if hard:
        c = Counter(r["level"] for r in hard if r["level"] != EXCLUDED)
        n = sum(c.values())
        print(f"\n[hardtest] {n} cặp khác chữ (holdout): " + "  ".join(f"m{k}={c.get(k, 0) / n:.2f}" for k in (3, 2, 1, 0)))
    old = {(r["a"], r["b"]): r["level"] for r in read_labels(out, "pool")}
    new = read_labels(out, "relabel")
    if new:
        ch = Counter((old[(r["a"], r["b"])], r["level"]) for r in new)
        print(f"\n[relabel] {len(new)} cặp gán lại · (cũ→mới): "
              + ", ".join(f"{a}→{b}: {c}" for (a, b), c in sorted(ch.items())))


def cmd_build(args) -> None:
    out = Path(args.out)
    arts, f, a_ids, b_ids, split = load_v3(Path(args.v3))
    lv, _ = _levels_buckets(arts, f, a_ids, b_ids)
    held = set(labels_by_pair(out, HELD_SETS))
    claude = {k: r["level"] for k, r in labels_by_pair(out, (*TRAIN_SETS, "relabel", *RECHECK_SETS)).items()}
    manual = manual_overrides(out)
    rng = np.random.default_rng(args.seed)
    rows = []
    for r in np.where(split == "train")[0]:
        key = (a_ids[r], b_ids[r])
        if key in held:
            continue
        if key in manual:                       # người dùng quyết định trực tiếp: ưu tiên cao nhất
            if manual[key] != EXCLUDED:
                rows.append((key, manual[key], "human"))
        elif key in claude:
            if claude[key] != EXCLUDED:
                rows.append((key, claude[key], "claude"))
        elif lv[r] in (3, 1):
            rows.append((key, int(lv[r]), "rule"))
    n_pos = sum(1 for _, v, _ in rows if v == 3)
    # cặp mức 0 do luật: lấy mẫu, nhưng bỏ cặp đã có nhãn Claude (ví dụ được gán lại thành 3) hoặc thuộc tập đo
    zero = np.array([r for r in np.where((split == "train") & (lv == 0))[0]
                     if (a_ids[r], b_ids[r]) not in claude and (a_ids[r], b_ids[r]) not in held
                     and (a_ids[r], b_ids[r]) not in manual], dtype=int)
    for r in rng.choice(zero, size=min(len(zero), args.zero_ratio * n_pos), replace=False):
        rows.append(((a_ids[r], b_ids[r]), 0, "rule"))
    with open(out / "graded_pairs.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps({"a_id": a, "b_id": b, "level": v, "score": LEVEL_SCORE[v], "source": src},
                                 ensure_ascii=False) + "\n" for (a, b), v, src in rows)
    rep = {"n_pairs": len(rows), "by_level": dict(Counter(v for _, v, _ in rows)),
           "by_level_source": {f"{v}|{s}": c for (v, s), c in Counter((v, s) for _, v, s in rows).items()},
           "rule_levels_all": dict(Counter(lv.tolist())), "params": vars(args)}
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))


BLIND_COLS = ["pair_no", "source_a", "date_a", "text_a", "source_b", "date_b", "text_b"]


def cmd_split(args) -> None:
    """<name>.csv → parts/<name>_NN.csv, mỗi phần --chunk cặp, để nhiều phiên Claude gán song song."""
    out = Path(args.out)
    (out / "parts").mkdir(exist_ok=True)
    with open(out / f"{args.name}.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for k, s in enumerate(range(0, len(rows), args.chunk)):
        cols = BLIND_COLS + [c for c in ("body_a", "body_b") if c in rows[0]]
        with open(out / "parts" / f"{args.name}_{k:02d}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows([r[c] for c in cols] for r in rows[s:s + args.chunk])
    print(f"{args.name}: {len(rows)} cặp → {k + 1} phần trong {out / 'parts'}/")


def cmd_merge(args) -> None:
    """parts/<name>_NN_labeled.csv → <name>_labeled.csv; báo cặp thiếu nhãn hoặc nhãn không hợp lệ."""
    out = Path(args.out)
    with open(out / f"{args.name}.csv", encoding="utf-8") as fh:
        want = [r["pair_no"] for r in csv.DictReader(fh)]
    got: dict[str, dict] = {}
    for part in sorted((out / "parts").glob(f"{args.name}_[0-9][0-9]_labeled.csv")):
        with open(part, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                got[r["pair_no"].strip()] = r
    bad = [k for k in want if k in got and parse_level(got[k].get("level", "")) is None]
    missing = [k for k in want if k not in got]
    with open(out / f"{args.name}_labeled.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pair_no", "level", "confidence", "reason"])
        w.writerows([k, got[k]["level"].strip(), got[k].get("confidence", "").strip(), got[k].get("reason", "")]
                    for k in want if k in got)
    lv = Counter(got[k]["level"].strip() for k in want if k in got)
    print(f"{args.name}: {len(want) - len(missing)}/{len(want)} cặp có nhãn {dict(lv)}"
          + (f" · THIẾU {len(missing)}: {missing[:10]}" if missing else "")
          + (f" · nhãn lỗi {bad[:10]}" if bad else ""))


HUMAN_COLS = ["pair_no", "source_a", "date_a", "title_a", "sapo_a", "source_b", "date_b", "title_b", "sapo_b",
              "gap_hours", "level_human", "ghi_chu"]


def cmd_human(args) -> None:
    """100 cặp từ tập test v4 (đã có nhãn Claude) để NGƯỜI gán mù → đo κ người ↔ Claude.

    Lấy đều theo nhãn Claude (mặc định 25 cặp mỗi mức) để mức hiếm (2) cũng đủ cặp mà đo; file của người KHÔNG có
    nhãn Claude — nhãn nằm ở human_label_100_ids.csv (đừng mở khi đang gán).
    """
    out = Path(args.out)
    src = args.from_set
    with open(out / f"{src}_ids.csv", encoding="utf-8") as fh:
        ids = {r["pair_no"]: r for r in csv.DictReader(fh)}
    with open(out / f"{src}_labeled.csv", encoding="utf-8-sig") as fh:
        lab = [r for r in csv.DictReader(fh) if parse_level(r["level"]) in (0, 1, 2, 3)]
    arts = {}
    with open(Path(args.v3) / "articles.jsonl", encoding="utf-8") as fh:
        for line in fh:
            a = json.loads(line)
            arts[a["article_id"]] = a
    rng = np.random.default_rng(args.seed)
    pick = []
    for lv in (3, 2, 1, 0):
        rows = [r for r in lab if int(r["level"]) == lv]
        pick += [rows[k] for k in rng.choice(len(rows), size=min(args.human_per_level, len(rows)), replace=False)]
    pick = [pick[k] for k in rng.permutation(len(pick))]
    path = out / f"{args.human_name}.csv"
    if path.exists() and not args.force:
        raise SystemExit(f"{path} đã có — không ghi đè (có thể bạn đã gán dở). Thêm --force nếu chắc chắn.")
    why = {"3": "cùng sự kiện", "2": "cùng câu chuyện, khác sự kiện", "1": "cùng chủ đề / khuôn tin", "0": "không liên quan"}
    with open(path, "w", encoding="utf-8-sig", newline="") as fh, \
            open(out / f"{args.human_name}_ids.csv", "w", encoding="utf-8", newline="") as gh:
        w, wi = csv.writer(fh), csv.writer(gh)
        cols = HUMAN_COLS[:-2] + (["level_goi_y"] if args.prefill else []) + HUMAN_COLS[-2:]
        w.writerow(cols)
        wi.writerow(["pair_no", "a", "b", "test_pair_no", "bucket", "level_claude", "source_set"])
        for k, r in enumerate(pick):
            i = ids[r["pair_no"]]
            A, B = arts[i["a"]], arts[i["b"]]
            gap = abs((datetime.fromisoformat(A["published_at"]) - datetime.fromisoformat(B["published_at"]))
                      .total_seconds()) / 3600
            sa, sb = (A["text"].split(". ", 1) + [""])[:2], (B["text"].split(". ", 1) + [""])[:2]
            lv = r["level"].strip()
            note = (f"[Claude gợi ý, độ tin {r.get('confidence', '')}] Mức {lv} = {why[lv]}. "
                    f"Cụ thể: {r.get('reason', '').strip()}")
            tail = [lv, lv, note] if args.prefill else ["", ""]
            w.writerow([k, A["source"], A["published_at"][:16].replace("T", " "), sa[0], sa[1],
                        B["source"], B["published_at"][:16].replace("T", " "), sb[0], sb[1], round(gap, 1), *tail])
            wi.writerow([k, i["a"], i["b"], r["pair_no"], i["bucket"], lv, src])
    print(f"{len(pick)} cặp → {path} (nhãn Claude để riêng ở {args.human_name}_ids.csv)")


def cmd_agree(args) -> None:
    """κ người ↔ Claude trên human_label_100.csv: 4 mức (không trọng số, trọng số bậc hai) và 2 mức (3 vs < 3)."""
    out = Path(args.out)
    with open(out / f"{args.human_name}_ids.csv", encoding="utf-8") as fh:
        ids = {r["pair_no"]: r for r in csv.DictReader(fh)}
    with open(out / f"{args.human_name}.csv", encoding="utf-8-sig") as fh:
        hum = list(csv.DictReader(fh))
    src = next(iter(ids.values())).get("source_set") or "test"
    with open(out / f"{src}_labeled.csv", encoding="utf-8-sig") as fh:
        reason = {r["pair_no"]: r.get("reason", "") for r in csv.DictReader(fh)}
    rows = []
    for r in hum:
        h = parse_level(r.get("level_human", ""))
        if h in (0, 1, 2, 3):
            rows.append((r, h, int(ids[r["pair_no"]]["level_claude"])))
    n_x = sum(parse_level(r.get("level_human", "")) == EXCLUDED for r in hum)
    if not rows:
        print("Chưa có cặp nào được gán (cột level_human đang trống).")
        return
    H = np.array([h for _, h, _ in rows])
    C = np.array([c for _, _, c in rows])
    rng = np.random.default_rng(0)

    def ci(fn):
        b = [fn(H[i], C[i]) for i in (rng.integers(0, len(H), len(H)) for _ in range(2000))]
        return np.nanpercentile(b, 2.5), np.nanpercentile(b, 97.5)

    k4 = lambda h, c: kappa(list(h), list(c))
    kq = lambda h, c: kappa(list(h), list(c), weights="quadratic")
    k2 = lambda h, c: kappa(list((h == 3).astype(int)), list((c == 3).astype(int)), levels=(0, 1))
    print(f"Số cặp so được: {len(rows)} (bỏ {n_x} cặp 'x', {len(hum) - len(rows) - n_x} cặp trống)")
    print(f"Trùng đúng mức: {(H == C).mean():.0%} · lệch ≤ 1 mức: {(np.abs(H - C) <= 1).mean():.0%}")
    for name, fn in (("κ 4 mức", k4), ("κ 4 mức, trọng số bậc hai", kq), ("κ 2 mức (cùng sự kiện hay không)", k2)):
        lo, hi = ci(fn)
        print(f"  {name:34s} = {fn(H, C):.3f}  CI95 [{lo:.3f}, {hi:.3f}]")
    print("Đọc κ: < 0,4 kém · 0,4–0,6 vừa · 0,6–0,8 tốt · > 0,8 rất tốt")
    print(f"Mẫu lấy đều theo mức Claude (tập {src}) → κ đo trên mẫu cân bằng, không phải trên tổng thể.")
    if "level_goi_y" in hum[0]:
        print("⚠ File có gợi ý sẵn của Claude (level_goi_y) → đây là đồng thuận SAU KHI DUYỆT, thường cao hơn gán mù "
              f"(hiệu ứng mỏ neo). Số cặp người đã sửa: {int((H != C).sum())}/{len(rows)}.")
    print("\nBảng nhầm lẫn (hàng = người, cột = Claude):\n        C3  C2  C1  C0")
    for h in (3, 2, 1, 0):
        print(f"  N{h}  " + "".join(f"{int(((H == h) & (C == c)).sum()):4d}" for c in (3, 2, 1, 0)))
    dis = [(r, h, c) for r, h, c in rows if h != c]
    with open(out / f"{args.human_name}_disagreements.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pair_no", "level_human", "level_claude", "title_a", "title_b", "ly_do_claude", "ghi_chu"])
        for r, h, c in sorted(dis, key=lambda x: -abs(x[1] - x[2])):
            w.writerow([r["pair_no"], h, c, r["title_a"], r["title_b"],
                        reason.get(ids[r["pair_no"]]["test_pair_no"], ""), r.get("ghi_chu", "")])
    print(f"\n{len(dis)} cặp lệch → {out / (args.human_name + '_disagreements.csv')} (xếp từ lệch xa nhất)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cmd", choices=["sample", "split", "merge", "build", "evaluate", "human", "agree", "relabel",
                                    "recheck", "consistency"])
    ap.add_argument("--silver-glob", default="data/lake/silver/*/*.jsonl")
    ap.add_argument("--body-chars", type=int, default=0,
                    help="sample/relabel: thêm N ký tự đầu thân bài vào file gán mù (0 = không; relabel mặc định 1000)")
    ap.add_argument("--test2-per-bucket", type=int, default=60)
    ap.add_argument("--pool2-template", type=int, default=380)
    ap.add_argument("--pool2-story", type=int, default=1300)
    ap.add_argument("--pool2-mid", type=int, default=1000)
    ap.add_argument("--pool2-low", type=int, default=320)
    ap.add_argument("--hard-dense", type=int, default=1000)
    ap.add_argument("--hard-other", type=int, default=500)
    ap.add_argument("--hardtest-dense", type=int, default=130)
    ap.add_argument("--hardtest-other", type=int, default=70)
    ap.add_argument("--human-per-level", type=int, default=25, help="human: số cặp mỗi mức (theo nhãn Claude)")
    ap.add_argument("--force", action="store_true", help="human: cho phép ghi đè file người gán")
    ap.add_argument("--from-set", default="test", help="human: lấy cặp từ tập nào (test | hardtest …)")
    ap.add_argument("--human-name", default="human_label_100", help="human/agree: tên file người gán")
    ap.add_argument("--prefill", action="store_true", help="human: điền sẵn gợi ý + lý do của Claude để người duyệt")
    ap.add_argument("--name", default="tune", help="split/merge: tune | test | pool")
    ap.add_argument("--chunk", type=int, default=50, help="split: số cặp mỗi phần")
    ap.add_argument("--select", default="conflicts", choices=["conflicts", "held", "train-sample", "train-all"],
                    help="consistency: chọn cặp nào để gán lại")
    ap.add_argument("--sample", type=int, default=150, help="consistency --select train-sample: số cặp mẫu")
    ap.add_argument("--v3", default="data/weak_labels/v3")
    ap.add_argument("--out", default="data/weak_labels/v4")
    ap.add_argument("--tune-per-bucket", type=int, default=25)
    ap.add_argument("--test-per-bucket", type=int, default=40)
    ap.add_argument("--sets", default="tune,test,pool", help="sample: các tập sinh (lại); tập khác giữ nguyên")
    ap.add_argument("--pool-template", type=int, default=300)
    ap.add_argument("--pool-story", type=int, default=500)
    ap.add_argument("--pool-mid", type=int, default=500)
    ap.add_argument("--pool-low", type=int, default=200)
    ap.add_argument("--zero-ratio", type=int, default=2, help="số cặp mức 0 / số cặp mức 3 trong file train")
    ap.add_argument("--seed", type=int, default=41)
    args = ap.parse_args(argv)
    if args.cmd == "relabel" and not args.body_chars:
        args.body_chars = 1000
    if args.cmd == "consistency" and args.name == "tune":
        args.name, args.chunk = "recheck2", 75
    if args.cmd in ("recheck", "consistency") and not args.body_chars:
        args.body_chars = 2000
    {"sample": cmd_sample, "split": cmd_split, "merge": cmd_merge, "build": cmd_build,
     "evaluate": cmd_evaluate, "human": cmd_human, "agree": cmd_agree, "relabel": cmd_relabel,
     "recheck": cmd_recheck, "consistency": cmd_consistency}[args.cmd](args)


if __name__ == "__main__":
    main()
