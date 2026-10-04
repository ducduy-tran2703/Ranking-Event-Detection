"""Sinh nhãn yếu "cặp cùng sự kiện" để fine-tune mô hình embedding.

    uv run python -m eventrank.weak_labels.build            # đọc data/lake/{gold,silver}
    uv run python -m eventrank.weak_labels.build --help

Chỉ đọc file cục bộ, chỉ ghi vào --out (mặc định data/weak_labels/v3/). Không chạm R2.
Tín hiệu ngữ nghĩa: chạy `make embed` trước; không có cache embedding thì LF ngữ nghĩa bỏ qua mọi cặp.

Đầu ra:
    articles.jsonl        bài + văn bản đưa vào embedding (tiêu đề. sapo) + split
    pairs.jsonl           mọi cặp ứng viên: xác suất, phiếu từng LF, đặc trưng
    train_triplets.jsonl  (anchor, positive, hard negative) cho MultipleNegativesRanking / GIST loss — p ≥ 0,80
    train_triplets_extended.jsonl  như trên với p ≥ 0,60 (cột tier: core/extended) — nhiều hơn, kém chính xác hơn
    train_pairs.jsonl     (a, b, score) đã cân bằng lớp, cho CoSENT / AnglE loss
    audit_sample.csv      cặp holdout lấy mẫu phân tầng để gán tay / LLM → đo chất lượng
    audit_ids.csv         pair_no ↔ article_id của audit_sample.csv (để không bao giờ phải ghép lại bằng tiêu đề)
    report.json           thống kê: độ phủ, độ chính xác ước lượng của từng LF, hiệu chỉnh

Từ score thô đến p cuối cùng:
    p_raw  = label model (Dawid–Skene)
    chặn   : thiếu nhóm bằng chứng dương (cùng báo cần ≥ 2), hoặc CHỈ có bằng chứng ngữ nghĩa → p ≤ 0,5
    phủ quyết (ngày, văn bản) → 0,02
    p      = hiệu chỉnh isotonic theo cặp có nhãn (--calibration), tách riêng cùng báo / khác báo
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from eventrank.weak_labels.corpus import Article, load_corpus
from eventrank.weak_labels.dense import DEFAULT_MODEL, load_dense
from eventrank.weak_labels.entities import EntityNormalizer, load_aliases
from eventrank.weak_labels.label_model import ABSTAIN, LabelModel
from eventrank.weak_labels.lfs import (
    LFS,
    VETO_P,
    apply_lfs,
    only_semantic,
    positive_families,
    set_dense_thresholds,
    veto_mask,
)
from eventrank.weak_labels.pairs import (
    FEATURES,
    dense_candidates,
    entity_candidates,
    pair_features,
    random_candidates,
    tfidf_candidates,
    tfidf_matrix,
)


def _log(msg: str, t0: float) -> None:
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


def assign_split(arts: list[Article], holdout_start: datetime, gap_h: float) -> list[str]:
    """Chia theo thời gian: train kết thúc trước cửa sổ holdout `gap_h` giờ → không rò rỉ cặp."""
    cut = holdout_start - timedelta(hours=gap_h)
    return ["holdout" if a.published_at >= holdout_start else "train" if a.published_at < cut
            else "gap" for a in arts]


def gate(p_raw: np.ndarray, n_fam: np.ndarray, cross: np.ndarray, same_dup: np.ndarray,
         veto: np.ndarray, min_families: int, min_families_same_source: int,
         semantic_only: np.ndarray | None = None) -> np.ndarray:
    """Chặn cặp dương thiếu bằng chứng độc lập; phủ quyết → 0,02.

    Cặp CÙNG BÁO cần nhiều bằng chứng hơn: một báo hay viết nhiều bài nối tiếp về cùng một giải đấu / một
    nhân vật (trùng thực thể nhưng khác sự kiện). Đo trên 399 cặp có nhãn: cặp cùng báo chỉ dựa trên 1 nhóm
    bằng chứng có precision 0,57; đòi ≥ 2 nhóm → 0,86. Cặp khác báo 1 nhóm đã đạt 0,82.
    Bài đăng lại (same_dup) thì một bằng chứng là đủ.
    """
    need = np.where(cross > 0, min_families, min_families_same_source)
    ok = (n_fam >= need) | (same_dup > 0)
    if semantic_only is not None:            # ngữ nghĩa chỉ được XÁC NHẬN, không được là bằng chứng duy nhất
        ok &= ~semantic_only
    p = np.where(ok, p_raw, np.minimum(p_raw, 0.5))
    return np.where(veto, np.minimum(p, VETO_P), p)


def finalize(p_cal: np.ndarray, gated: np.ndarray, veto: np.ndarray) -> np.ndarray:
    """Áp lại chốt chặn SAU hiệu chỉnh: isotonic có thể ánh xạ điểm 0,5 của cặp bị chặn thành > 0,5
    (đã gặp: 0,5 → 0,68 với cặp khác báo), làm cặp bị chặn lọt lại vào tầng dương."""
    return np.where(veto, np.minimum(p_cal, VETO_P), np.where(gated, np.minimum(p_cal, 0.5), p_cal))


class Calibrator:
    """Isotonic regression score → tỉ lệ cùng sự kiện thật, fit riêng cho cùng báo và khác báo."""

    def __init__(self, min_group: int = 60):
        self.min_group = min_group
        self.models: dict[int | str, object] = {}

    def fit(self, score: np.ndarray, cross: np.ndarray, y: np.ndarray) -> Calibrator:
        from sklearn.isotonic import IsotonicRegression

        def _fit(m):
            return IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(score[m], y[m])

        self.models["all"] = _fit(np.ones(len(y), bool))
        for g in (0, 1):
            m = cross == g
            if m.sum() >= self.min_group:
                self.models[g] = _fit(m)
        return self

    def transform(self, score: np.ndarray, cross: np.ndarray) -> np.ndarray:
        out = self.models["all"].predict(score)
        for g in (0, 1):
            if g in self.models:
                m = cross == g
                out[m] = self.models[g].predict(score[m])
        return out


def _read_labeled(path: str | Path) -> list[tuple[str, str, int]]:
    """CSV có cột a, b (article_id) và label_llm hoặc label_human (0/1)."""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            y = (r.get("label_human") or r.get("label_llm") or "").strip()
            if y in ("0", "1"):
                out.append((r["a"], r["b"], int(y)))
    return out


NEG_CONTENT_COS = 0.15       # negative phải khác CẢ từ vựng (cos_lead < 0,15) LẪN thực thể (ent_wjacc < 0,10)
NEG_CONTENT_WJACC = 0.10


def content_negative(feats: dict) -> np.ndarray:
    """Cặp có bằng chứng KHÁC NỘI DUNG (không chỉ "cách xa thời gian").

    Đo bằng Claude gán mù trên negative khó của v2:
      - chỉ dựa vào p thấp: 29/100 negative là cùng sự kiện — gần như tất cả chỉ có phiếu âm từ lf_time_far
        (cách > 72h) trong khi nội dung rất giống: tin tiếp nối nhiều ngày của cùng một vụ việc;
      - đòi khác nội dung theo MỘT tiêu chí (cos HOẶC wjacc): còn 12/100 sai — phần lớn là các khía cạnh của
        một sự kiện lớn nhiều ngày (chuyến thăm cấp Nhà nước, phiên toà nhiều bị cáo);
      - đòi khác theo CẢ HAI tiêu chí: ~5% sai trên mẫu thứ hai, ≤ 1/29 trên mẫu thứ nhất.
    """
    return (feats["cos_lead"] < NEG_CONTENT_COS) & (feats["ent_wjacc"] < NEG_CONTENT_WJACC)


def select_training(arts, pairs, p, feats, split, pos_th, neg_th, max_pos_per_anchor, neg_ratio,
                    seed, neg_margin=0.95, neg_max_dense=0.55):
    """Bộ ba (anchor, positive, negative khó) + cặp có điểm đã cân bằng lớp. Chỉ dùng cặp split=train.

    Negative khó phải có độ giống anchor < neg_margin × độ giống (anchor, positive) — kiểu "TopK-PercPos"
    của NV-Retriever. Bài GIỐNG anchor hơn cả positive mà p vẫn thấp thường là cặp dương bị bỏ sót (recall
    của nhãn yếu chỉ ~40%), dùng nó làm negative là dạy mô hình đẩy hai bài cùng sự kiện ra xa nhau.
    """
    sim = np.where(np.isnan(feats["cos_dense"]), feats["cos_lead"], feats["cos_dense"])
    usable_neg = (p <= neg_th) & content_negative(feats)
    # Có embedding: negative còn phải KHÁC NGHĨA. Bài "cùng nghĩa, khác chữ" chính là loại dương mà nhãn yếu
    # hay bỏ sót; xếp negative theo độ giống ngữ nghĩa mà không chặn thì sẽ chọn trúng chúng.
    usable_neg &= ~(np.nan_to_num(feats["cos_dense"], nan=-1.0) >= neg_max_dense)
    nb: dict[int, list[tuple[float, int, float]]] = defaultdict(list)
    pos_nb: dict[int, set[int]] = defaultdict(set)          # láng giềng "có thể cùng sự kiện" (p > 0,5)
    pmap: dict[tuple[int, int], float] = {}
    for r, (i, j) in enumerate(pairs):
        i, j = int(i), int(j)
        pmap[(i, j)] = p[r]
        # p của negative ứng viên = p thật nếu có bằng chứng khác nội dung, ngược lại coi như không dùng được
        pn = p[r] if usable_neg[r] else 1.0
        nb[i].append((sim[r], j, pn))
        nb[j].append((sim[r], i, pn))
        if p[r] > 0.5:
            pos_nb[i].add(j)
            pos_nb[j].add(i)
    for v in nb.values():
        v.sort(reverse=True)                       # negative "khó" = giống anchor nhất

    def is_train(*ids):
        return all(split[x] == "train" for x in ids)

    def safe_negative(a, b, c):
        """c khác sự kiện với a, b, VÀ không nối với a/b qua một bài trung gian (A~X~C)."""
        near = pos_nb[a] | pos_nb[b] | {a, b}
        return c not in near and not (pos_nb[c] & near)

    used = Counter()
    triplets, positives = [], []
    for r in np.argsort(-p):
        i, j = map(int, pairs[r])
        if p[r] < pos_th:
            break
        if not is_train(i, j) or feats["same_dup"][r]:
            continue
        positives.append((i, j, float(p[r])))
        if used[i] >= max_pos_per_anchor:
            continue
        used[i] += 1
        cap = neg_margin * sim[r]
        neg = next((c for sc, c, pc in nb[i] if sc < cap and pc <= neg_th and is_train(c)
                    and safe_negative(i, j, c)), None)
        triplets.append((i, j, neg, float(p[r])))
    # Cặp có điểm: mọi cặp dương + tối đa neg_ratio cặp âm/cặp dương, ưu tiên âm KHÓ (giống nhau nhất)
    negs = sorted(((sim[r], int(i), int(j), float(p[r])) for r, (i, j) in enumerate(pairs)
                   if usable_neg[r] and is_train(int(i), int(j))), reverse=True)
    n_neg = min(len(negs), neg_ratio * len(positives))
    n_hard = n_neg // 2                             # một nửa âm khó nhất, một nửa ngẫu nhiên
    rng = np.random.default_rng(seed)
    rest = negs[n_hard:]
    pick = [rest[k] for k in rng.choice(len(rest), size=min(n_neg - n_hard, len(rest)), replace=False)]
    soft = positives + [(i, j, pr) for _, i, j, pr in negs[:n_hard] + pick]
    return triplets, soft


def audit_sample(pairs, p, feats, split, n_per_bin, seed, exclude: set[frozenset]):
    """Lấy mẫu phân tầng theo p × (cùng báo / khác báo) từ HOLDOUT, bỏ các cặp đã dùng để hiệu chỉnh."""
    rng = np.random.default_rng(seed)
    bins = [(0.0, 0.1), (0.1, 0.5), (0.5, 0.8), (0.8, 1.01)]
    hold = np.array([split[i] == "holdout" and split[j] == "holdout" for i, j in pairs])
    rows = []
    for lo, hi in bins:
        for cross in (0, 1):
            m = [r for r in np.where(hold & (p >= lo) & (p < hi) & (feats["cross_source"] == cross))[0]
                 if frozenset(map(int, pairs[r])) not in exclude]
            for r in rng.choice(m, size=min(n_per_bin, len(m)), replace=False) if m else []:
                rows.append((int(r), f"{lo:.2f}-{min(hi, 1):.2f}", cross))
    rng.shuffle(rows)
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--gold", default="data/lake/gold/gold_data.jsonl")
    ap.add_argument("--silver-glob", default="data/lake/silver/*/*.jsonl")
    ap.add_argument("--aliases", default="configs/entity_aliases.yaml")
    ap.add_argument("--out", default="data/weak_labels/v3")
    ap.add_argument("--dense-model", default=DEFAULT_MODEL)
    ap.add_argument("--cache-dir", default="data/weak_labels/cache")
    ap.add_argument("--no-dense", action="store_true", help="bỏ tín hiệu ngữ nghĩa dù có cache")
    ap.add_argument("--window-hours", type=float, default=168, help="cửa sổ sinh ứng viên")
    ap.add_argument("--holdout-start", default="2026-09-13T00:00:00+07:00",
                    help="bài từ mốc này trở đi dành cho đánh giá, không dùng để huấn luyện")
    ap.add_argument("--gap-hours", type=float, default=48)
    ap.add_argument("--prior", type=float, default=0.10,
                    help="tỉ lệ cặp cùng sự kiện trong tập ứng viên (cố định, không để EM tự học)")
    ap.add_argument("--min-families", type=int, default=1,
                    help="số nhóm bằng chứng dương độc lập tối thiểu (cặp KHÁC báo)")
    ap.add_argument("--min-families-same-source", type=int, default=2,
                    help="như trên, cho cặp CÙNG báo")
    ap.add_argument("--calibration", default="data/weak_labels/v1/audit_labeled_llm_ids.csv",
                    help="CSV cặp có nhãn (a, b, label_llm|label_human) để hiệu chỉnh p; '' = không hiệu chỉnh")
    ap.add_argument("--pos-threshold", type=float, default=0.80, help="trên p ĐÃ hiệu chỉnh")
    ap.add_argument("--ext-threshold", type=float, default=0.60,
                    help="ngưỡng cho train_triplets_extended.jsonl (nhiều dữ liệu hơn, precision thấp hơn)")
    ap.add_argument("--neg-threshold", type=float, default=0.10)
    ap.add_argument("--max-pos-per-anchor", type=int, default=3)
    ap.add_argument("--neg-ratio", type=int, default=3, help="số cặp âm / cặp dương trong train_pairs")
    ap.add_argument("--dense-pos", type=float, default=0.80, help="ngưỡng cosine cho phiếu DƯƠNG ngữ nghĩa")
    ap.add_argument("--dense-neg", type=float, default=0.30, help="ngưỡng cosine cho phiếu ÂM ngữ nghĩa")
    ap.add_argument("--neg-max-dense", type=float, default=0.55,
                    help="negative phải có cosine ngữ nghĩa < giá trị này (khi có embedding)")
    ap.add_argument("--force-pairs", default="",
                    help="CSV (a, b) các cặp bắt buộc có trong tập ứng viên — ví dụ mẫu audit cần đo lại")
    ap.add_argument("--neg-margin", type=float, default=0.95,
                    help="negative phải có độ giống anchor < neg_margin × độ giống của positive")
    ap.add_argument("--audit-per-bin", type=int, default=50)
    ap.add_argument("--seed", type=int, default=29)
    args = ap.parse_args(argv)
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    normalizer = EntityNormalizer(load_aliases(args.aliases))
    arts, idf, _ = load_corpus(args.gold, args.silver_glob, normalizer)
    n = len(arts)
    pos_of = {a.article_id: a.idx for a in arts}
    _log(f"nạp {n} bài, {len(idf)} thực thể chuẩn hoá ({sum(v == 0 for v in idf.values())} có idf=0)", t0)

    E = None if args.no_dense else load_dense(args.cache_dir, args.dense_model,
                                              [a.article_id for a in arts])
    _log(f"embedding ngữ nghĩa: {'có (' + args.dense_model + ')' if E is not None else 'KHÔNG có'}", t0)

    set_dense_thresholds(args.dense_pos, args.dense_neg)
    labeled = _read_labeled(args.calibration) if args.calibration else []
    labeled = [(pos_of[a], pos_of[b], y) for a, b, y in labeled if a in pos_of and b in pos_of]
    forced = {(min(i, j), max(i, j)) for i, j, _ in labeled}
    if args.force_pairs:
        with open(args.force_pairs, encoding="utf-8-sig") as f:
            forced |= {(min(pos_of[r["a"]], pos_of[r["b"]]), max(pos_of[r["a"]], pos_of[r["b"]]))
                       for r in csv.DictReader(f) if r["a"] in pos_of and r["b"] in pos_of}

    X_head = tfidf_matrix([a.head_text() for a in arts])
    X_lead = tfidf_matrix([f"{a.head_text()} {a.lead}" for a in arts])
    cand = {"entity": entity_candidates(arts, args.window_hours),
            "tfidf": tfidf_candidates(arts, X_lead, args.window_hours),
            "random": random_candidates(arts, seed=args.seed)}
    if E is not None:
        cand["dense"] = dense_candidates(arts, E, args.window_hours)
    allc = set().union(*cand.values()) | forced
    pairs = np.array(sorted(allc), dtype=np.int64)
    _log("ứng viên: " + ", ".join(f"{k} {len(v)}" for k, v in cand.items())
         + f", bắt buộc {len(forced)} → hợp {len(pairs)}", t0)

    feats = pair_features(arts, pairs, X_head, X_lead, rare_idf=math.log(n / 200), idf=idf, E=E)
    L = apply_lfs(feats)
    lm = LabelModel(prior=args.prior).fit(L)
    p_raw = lm.predict_proba(L)
    n_fam = positive_families(L)
    veto = veto_mask(feats)
    sem_only = only_semantic(L)
    score = gate(p_raw, n_fam, feats["cross_source"], feats["same_dup"], veto, args.min_families,
                 args.min_families_same_source, sem_only)
    _log(f"label model: prior={lm.prior:.3f}; phủ quyết {int(veto.sum())}; "
         f"bị chặn vì thiếu nhóm bằng chứng {int(((score < p_raw) & ~veto).sum())}", t0)

    calib_info = None
    if labeled:
        row = {(int(i), int(j)): r for r, (i, j) in enumerate(pairs)}
        idx = np.array([row[(min(i, j), max(i, j))] for i, j, _ in labeled])
        y = np.array([yy for _, _, yy in labeled])
        cal = Calibrator().fit(score[idx], feats["cross_source"][idx], y)
        p = finalize(cal.transform(score, feats["cross_source"]), (score < p_raw) & ~veto, veto)
        calib_info = {"n_labeled": len(y), "groups": sorted(map(str, cal.models)),
                      "source": args.calibration}
        _log(f"hiệu chỉnh isotonic trên {len(y)} cặp có nhãn", t0)
    else:
        p = score

    split = assign_split(arts, datetime.fromisoformat(args.holdout_start), args.gap_hours)
    triplets, soft = select_training(arts, pairs, p, feats, split, args.pos_threshold,
                                     args.neg_threshold, args.max_pos_per_anchor, args.neg_ratio,
                                     args.seed, args.neg_margin, args.neg_max_dense)

    triplets_ext, _ = select_training(arts, pairs, p, feats, split, args.ext_threshold,
                                      args.neg_threshold, args.max_pos_per_anchor, args.neg_ratio,
                                      args.seed, args.neg_margin, args.neg_max_dense)

    # ---- ghi file
    with open(out / "articles.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps({"article_id": a.article_id, "source": a.source,
                                 "category": a.category, "published_at": a.published_at.isoformat(),
                                 "split": split[a.idx], "dup_group": arts[a.dup_group].article_id,
                                 "text": a.head_text()}, ensure_ascii=False) + "\n" for a in arts)
    names = [lf.__name__ for lf in LFS]
    with open(out / "pairs.jsonl", "w", encoding="utf-8") as f:
        for r, (i, j) in enumerate(pairs):
            rec = {"a": arts[i].article_id, "b": arts[j].article_id, "p": round(float(p[r]), 4),
                   "p_raw": round(float(p_raw[r]), 4), "n_pos_families": int(n_fam[r]),
                   "vetoed": bool(veto[r]),
                   "split": split[i] if split[i] == split[j] else "mixed",
                   "votes": {nm: int(L[r, k]) for k, nm in enumerate(names) if L[r, k] != ABSTAIN}}
            rec.update({k: (None if np.isnan(feats[k][r]) else round(float(feats[k][r]), 4))
                        for k in FEATURES})
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(out / "train_triplets.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps({"anchor_id": arts[i].article_id, "positive_id": arts[j].article_id,
                                 "negative_id": arts[c].article_id if c is not None else None,
                                 "anchor": arts[i].head_text(), "positive": arts[j].head_text(),
                                 "negative": arts[c].head_text() if c is not None else None,
                                 "p": round(pr, 4)}, ensure_ascii=False) + "\n"
                     for i, j, c, pr in triplets)
    with open(out / "train_triplets_extended.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps({"anchor_id": arts[i].article_id, "positive_id": arts[j].article_id,
                                 "negative_id": arts[c].article_id if c is not None else None,
                                 "anchor": arts[i].head_text(), "positive": arts[j].head_text(),
                                 "negative": arts[c].head_text() if c is not None else None,
                                 "p": round(pr, 4),
                                 "tier": "core" if pr >= args.pos_threshold else "extended"},
                                ensure_ascii=False) + "\n" for i, j, c, pr in triplets_ext)
    with open(out / "train_pairs.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps({"a_id": arts[i].article_id, "b_id": arts[j].article_id,
                                 "a": arts[i].head_text(), "b": arts[j].head_text(),
                                 "label": int(pr >= args.pos_threshold), "score": round(pr, 4)},
                                ensure_ascii=False) + "\n" for i, j, pr in soft)
    exclude = {frozenset((i, j)) for i, j, _ in labeled}
    audit = audit_sample(pairs, p, feats, split, args.audit_per_bin, args.seed, exclude)
    with open(out / "audit_sample.csv", "w", encoding="utf-8", newline="") as f, \
            open(out / "audit_ids.csv", "w", encoding="utf-8", newline="") as g:
        w, wi = csv.writer(f), csv.writer(g)
        w.writerow(["pair_no", "p_bin", "p", "cross_source", "dt_hours", "source_a", "title_a",
                    "sapo_a", "source_b", "title_b", "sapo_b", "label_human (1/0/?)"])
        wi.writerow(["pair_no", "a", "b", "p", "p_bin", "cross_source"])
        for k, (r, b, cross) in enumerate(audit):
            A, B = arts[pairs[r, 0]], arts[pairs[r, 1]]
            w.writerow([k, b, round(float(p[r]), 3), cross, round(float(feats["dt_hours"][r]), 1),
                        A.source, A.title, A.sapo[:300], B.source, B.title, B.sapo[:300], ""])
            wi.writerow([k, A.article_id, B.article_id, round(float(p[r]), 4), b, cross])

    # ---- báo cáo
    pos = p >= args.pos_threshold
    tr_pos = [(i, j) for i, j, _, _ in triplets]
    n_soft_pos = sum(pr >= args.pos_threshold for _, _, pr in soft)
    report = {
        "n_articles": n, "split_articles": dict(Counter(split)),
        "dense_model": args.dense_model if E is not None else None,
        "n_candidates": len(pairs),
        "candidate_sources": {k: len(v) for k, v in cand.items()} | {"forced": len(forced)},
        "label_model_prior": round(lm.prior, 4),
        "lf": {nm: {"coverage": round(float((L[:, k] != ABSTAIN).mean()), 4),
                    "pos_votes": int((L[:, k] == 1).sum()), "neg_votes": int((L[:, k] == 0).sum()),
                    "est_accuracy": round(float(lm.accuracies()[k]), 4)}
               for k, nm in enumerate(names)},
        "vetoed_pairs": int(veto.sum()),
        "gated_by_families": int(((score < p_raw) & ~veto).sum()),
        "gated_semantic_only": int((sem_only & (p_raw > 0.5)).sum()),
        "calibration": calib_info,
        "conflict_rate": round(float(((L == 1).any(1) & (L == 0).any(1)).mean()), 4),
        "no_vote_rate": round(float((L == ABSTAIN).all(1).mean()), 4),
        "p_histogram": {f"{lo / 10:.1f}": int(((p >= lo / 10) & (p < (lo + 1) / 10 + (lo == 9))).sum())
                        for lo in range(10)},
        "positives_all": int(pos.sum()),
        "positives_cross_source": round(float(feats["cross_source"][pos].mean()), 4) if pos.any() else 0,
        "positives_same_category": round(float(feats["same_category"][pos].mean()), 4) if pos.any() else 0,
        "positives_families": {str(k): int(v) for k, v in sorted(Counter(n_fam[pos]).items())},
        "train_triplets": len(triplets),
        "train_triplets_with_negative": sum(c is not None for _, _, c, _ in triplets),
        "train_cross_source": round(float(np.mean([arts[i].source != arts[j].source
                                                   for i, j in tr_pos])) if tr_pos else 0, 4),
        "train_anchor_articles": len({i for i, _ in tr_pos}),
        "train_soft_pairs": len(soft), "train_soft_positive": n_soft_pos,
        "train_triplets_extended": len(triplets_ext),
        "train_triplets_extended_core": sum(pr >= args.pos_threshold for _, _, _, pr in triplets_ext),
        "audit_rows": len(audit),
        "params": vars(args),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"xong → {out}/", t0)
    print(json.dumps({k: v for k, v in report.items() if k not in ("params", "lf")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
