"""Sinh cặp ứng viên và tính đặc trưng cho từng cặp.

So mọi cặp (28k² / 2 ≈ 400 triệu) là không cần thiết: hai bài cùng sự kiện gần như luôn đăng cách nhau
vài ngày. Ứng viên lấy từ ba nguồn, đều giới hạn trong cửa sổ thời gian:
  1. chung thực thể hiếm và nổi bật (chỉ mục ngược)
  2. láng giềng TF-IDF gần nhất  → bắt các cặp cùng sự kiện nhưng NER không khớp
  3. ngẫu nhiên trong ±24h       → cặp âm "bình thường", để label model thấy đủ hai lớp
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

from eventrank.weak_labels.corpus import Article

_NUM = re.compile(
    r"(\d+(?:[.,]\d+)*)\s*(người|tỷ|triệu|nghìn|ngàn|ha|km|%|tấn|căn|ca|học sinh|usd|đồng|tuổi|"
    r"năm tù|chiếc|xe|hộ|bệnh nhân|trẻ|cm|mm|m)\b", re.IGNORECASE)

_DATE = re.compile(r"(?<![\d.,/-])(\d{1,2})[./-](\d{1,2})(?:[./-](?:\d{4}|\d{2}))?(?![\d/-])")
# Ngày lễ đứng ngay trước ngày tháng ("Quốc khánh 2/9"). KHÔNG gồm chữ "ngày": "Giá vàng ngày 16/9" là ngày đăng
_HOLIDAY = re.compile(r"(quốc khánh|khánh|giải phóng)\s*$", re.IGNORECASE)
_SCORE_CTX = re.compile(r"(thắng|thua|hòa|hoà|tỉ số|tỷ số|bàn|set)\s*$", re.IGNORECASE)

FEATURES = ["dt_hours", "cross_source", "same_category", "same_dup", "ent_score", "ent_wjacc",
            "n_head_shared", "cos_head", "cos_lead", "n_numbers", "date_conflict", "cos_dense",
            "conflict_doc", "conflict_org", "conflict_per", "conflict_event", "conflict_loc"]
CONFLICT_LABELS = {"DOC": "conflict_doc", "ORG": "conflict_org", "PER": "conflict_per",
                   "EVENT": "conflict_event", "LOC": "conflict_loc"}


def title_dates(title: str) -> set[tuple[int, int]]:
    """Ngày/tháng ghi trong tiêu đề ("hôm nay 8.9.2026", "tối 10-9"). Bỏ ngày lễ và tỉ số."""
    out = set()
    for m in _DATE.finditer(title):
        d, mo = int(m.group(1)), int(m.group(2))
        before = title[:m.start()]
        if not (1 <= d <= 31 and 1 <= mo <= 12) or _HOLIDAY.search(before) or _SCORE_CTX.search(before):
            continue
        out.add((d, mo))
    return out


def numbers(text: str) -> set[str]:
    """Con số cụ thể kèm đơn vị: "15 người", "2,5 tỷ". Năm (2026) và số trần không tính."""
    return {f"{m.group(1).replace(',', '.')} {m.group(2).lower()}" for m in _NUM.finditer(text)}


def _key_ok(a: Article, k: str) -> bool:
    e = a.entities[k]
    return e.in_head or e.mentions >= 2 or e.best_zone == "lead"


def entity_candidates(arts: list[Article], window_h: float, max_posting: int = 400,
                      top_k: int = 20) -> set[tuple[int, int]]:
    posting: dict[str, list[int]] = defaultdict(list)
    for a in arts:
        for k in a.weights:
            if _key_ok(a, k):
                posting[k].append(a.idx)
    score: dict[tuple[int, int], float] = defaultdict(float)
    w = window_h * 3600
    for k, ids in posting.items():
        if len(ids) < 2 or len(ids) > max_posting:
            continue
        ids.sort(key=lambda i: arts[i].ts)
        for x, i in enumerate(ids):
            ti = arts[i].ts
            for j in ids[x + 1:]:
                if arts[j].ts - ti > w:
                    break
                score[(min(i, j), max(i, j))] += min(arts[i].weights[k], arts[j].weights[k])
    per: dict[int, list[tuple[float, tuple[int, int]]]] = defaultdict(list)
    for p, s in score.items():
        per[p[0]].append((s, p))
        per[p[1]].append((s, p))
    keep: set[tuple[int, int]] = set()
    for lst in per.values():
        lst.sort(reverse=True)
        keep.update(p for _, p in lst[:top_k])
    return keep


def tfidf_matrix(texts: list[str]) -> sparse.csr_matrix:
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.3, sublinear_tf=True,
                          lowercase=True, token_pattern=r"(?u)\b\w+\b")
    return vec.fit_transform(texts).tocsr()


def tfidf_candidates(arts: list[Article], X: sparse.csr_matrix, window_h: float, k: int = 10,
                     chunk: int = 1000) -> set[tuple[int, int]]:
    ts = np.array([a.ts for a in arts])
    w = window_h * 3600
    out: set[tuple[int, int]] = set()
    XT = X.T.tocsc()
    for s in range(0, X.shape[0], chunk):
        sims = (X[s:s + chunk] @ XT).toarray()
        for r in range(sims.shape[0]):
            i = s + r
            row = sims[r]
            row[np.abs(ts - ts[i]) > w] = 0
            row[i] = 0
            for j in np.argpartition(-row, k)[:k]:
                if row[j] > 0.15:
                    out.add((min(i, int(j)), max(i, int(j))))
    return out


def random_candidates(arts: list[Article], window_h: float = 24, per_article: int = 1,
                      seed: int = 0) -> set[tuple[int, int]]:
    rng = np.random.default_rng(seed)
    order = sorted(range(len(arts)), key=lambda i: arts[i].ts)
    ts = np.array([arts[i].ts for i in order])
    out: set[tuple[int, int]] = set()
    for pos, i in enumerate(order):
        lo = np.searchsorted(ts, ts[pos] - window_h * 3600)
        hi = np.searchsorted(ts, ts[pos] + window_h * 3600)
        if hi - lo < 2:
            continue
        for j in rng.integers(lo, hi, per_article):
            j = order[int(j)]
            if j != i:
                out.add((min(i, j), max(i, j)))
    return out


def dense_candidates(arts: list[Article], E: np.ndarray, window_h: float, k: int = 10,
                     min_sim: float = 0.6, chunk: int = 1000) -> set[tuple[int, int]]:
    """Láng giềng gần nhất theo embedding ngữ nghĩa: bắt cặp cùng sự kiện nhưng viết khác nhau."""
    ts = np.array([a.ts for a in arts])
    w = window_h * 3600
    out: set[tuple[int, int]] = set()
    for s in range(0, len(arts), chunk):
        sims = E[s:s + chunk] @ E.T
        for r in range(sims.shape[0]):
            i = s + r
            row = sims[r]
            row[np.abs(ts - ts[i]) > w] = -1
            row[i] = -1
            for j in np.argpartition(-row, k)[:k]:
                if row[j] >= min_sim:
                    out.add((min(i, int(j)), max(i, int(j))))
    return out


def title_conflicts(A: Article, B: Article) -> dict[str, int]:
    """Mỗi tiêu đề có một thực thể cùng loại mà bài kia KHÔNG HỀ nhắc tới (kể cả trong thân bài).

    "Kế hoạch thi hành Luật Hòa giải" ↔ "… Luật Phát triển đô thị" (DOC); "U23 VN gặp Kuwait" ↔ "… gặp
    Philippines" (ORG). Điều kiện "không hề nhắc" giữ lại cặp đúng kiểu "Bộ Y tế đề nghị…" ↔ "Cục ATTP
    yêu cầu…" khi bài này có nhắc cơ quan kia ở thân bài.
    """
    out = {}
    for label, name in CONFLICT_LABELS.items():
        ta = {k for k, e in A.entities.items() if e.label == label and e.best_zone == "title"
              and k in A.weights}
        tb = {k for k, e in B.entities.items() if e.label == label and e.best_zone == "title"
              and k in B.weights}
        out[name] = int(bool(ta - B.entities.keys()) and bool(tb - A.entities.keys()))
    return out


def _rowdot(X: sparse.csr_matrix, a: np.ndarray, b: np.ndarray, chunk: int = 200_000) -> np.ndarray:
    out = np.empty(len(a))
    for s in range(0, len(a), chunk):
        out[s:s + chunk] = np.asarray(X[a[s:s + chunk]].multiply(X[b[s:s + chunk]]).sum(1)).ravel()
    return out


def pair_features(arts: list[Article], pairs: np.ndarray, X_head: sparse.csr_matrix,
                  X_lead: sparse.csr_matrix, rare_idf: float, idf: dict[str, float],
                  E: np.ndarray | None = None) -> dict:
    a_idx, b_idx = pairs[:, 0], pairs[:, 1]
    nums = [numbers(f"{a.title} {a.sapo}") for a in arts]
    dates = [title_dates(a.title) for a in arts]
    f = {k: np.zeros(len(pairs)) for k in FEATURES}
    for r, (i, j) in enumerate(pairs):
        A, B = arts[i], arts[j]
        f["dt_hours"][r] = abs(A.ts - B.ts) / 3600
        f["cross_source"][r] = A.source != B.source
        f["same_category"][r] = A.category == B.category
        f["same_dup"][r] = A.dup_group == B.dup_group
        wa, wb = A.weights, B.weights
        shared = wa.keys() & wb.keys()
        mn = sum(min(wa[k], wb[k]) for k in shared)
        mx = sum(max(wa.get(k, 0), wb.get(k, 0)) for k in wa.keys() | wb.keys())
        f["ent_score"][r] = mn
        f["ent_wjacc"][r] = mn / mx if mx else 0.0
        f["n_head_shared"][r] = sum(1 for k in shared if A.entities[k].in_head
                                    and B.entities[k].in_head and idf[k] >= rare_idf)
        f["n_numbers"][r] = len(nums[i] & nums[j])
        f["date_conflict"][r] = bool(dates[i]) and bool(dates[j]) and not (dates[i] & dates[j])
        for name, v in title_conflicts(A, B).items():
            f[name][r] = v
    f["cos_head"] = _rowdot(X_head, a_idx, b_idx)
    f["cos_lead"] = _rowdot(X_lead, a_idx, b_idx)
    # NaN = không có embedding → LF ngữ nghĩa bỏ qua
    f["cos_dense"] = (np.einsum("ij,ij->i", E[a_idx], E[b_idx]) if E is not None
                      else np.full(len(pairs), np.nan))
    return f
