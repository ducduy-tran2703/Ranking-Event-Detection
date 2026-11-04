"""Đo precision / recall của nhãn yếu trên một mẫu audit phân tầng, có trọng số theo kích thước tầng.

    uv run python -m eventrank.weak_labels.evaluate \\
        --audit data/weak_labels/v2/audit_labeled_llm.csv --population data/weak_labels/v2/pairs.jsonl \\
        --system v2=data/weak_labels/v2/pairs.jsonl --system v3=data/weak_labels/v3/pairs.jsonl

Mẫu audit lấy ĐỀU n cặp mỗi tầng (khoảng p × cùng/khác báo) trong khi các tầng có kích thước rất khác nhau, nên
tỉ lệ thô trên mẫu KHÔNG phải precision/recall thật. Mỗi cặp được nhân trọng số N_tầng / n_tầng (ước lượng
Horvitz–Thompson). Tổng thể = các cặp ứng viên holdout của hệ thống đã sinh ra mẫu (--population), trừ các cặp
dùng để hiệu chỉnh (--exclude). CI 95% bằng bootstrap lấy mẫu lại TRONG từng tầng.

Giới hạn: cặp cùng sự kiện không nằm trong tập ứng viên của --population thì không đo được (recall ở đây là
recall TRONG tập ứng viên đó).
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict

import numpy as np

BINS = [(0.0, 0.1), (0.1, 0.5), (0.5, 0.8), (0.8, 1.01)]


def bin_of(p: float) -> str:
    for lo, hi in BINS:
        if lo <= p < hi:
            return f"{lo:.2f}-{min(hi, 1):.2f}"
    raise ValueError(p)


def weighted_pr(strata: dict[str, list[tuple[int, int]]], sizes: dict[str, int]) -> tuple[float, float]:
    """strata: tầng → [(y_thật, dự_đoán_dương)]; sizes: tầng → số cặp trong tổng thể. Trả (precision, recall)."""
    tp = pos = pred = 0.0
    for s, rows in strata.items():
        if not rows:
            continue
        w = sizes.get(s, 0) / len(rows)
        tp += w * sum(y * d for y, d in rows)
        pos += w * sum(y for y, _ in rows)
        pred += w * sum(d for _, d in rows)
    return (tp / pred if pred else float("nan"), tp / pos if pos else float("nan"))


def _load_p(path: str) -> dict[frozenset, dict]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out[frozenset((r["a"], r["b"]))] = r
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--audit", default="data/weak_labels/v2/audit_labeled_llm.csv")
    ap.add_argument("--population", default="data/weak_labels/v2/pairs.jsonl")
    ap.add_argument("--exclude", default="data/weak_labels/v1/audit_labeled_llm_ids.csv")
    ap.add_argument("--system", action="append", required=True, help="tên=đường_dẫn_pairs.jsonl")
    ap.add_argument("--pos-threshold", type=float, default=0.80)
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args(argv)

    excl = set()
    if args.exclude:
        with open(args.exclude, encoding="utf-8-sig") as f:
            excl = {frozenset((r["a"], r["b"])) for r in csv.DictReader(f)}
    pop = _load_p(args.population)
    sizes = Counter(f"{bin_of(r['p'])}|{int(r['cross_source'])}" for k, r in pop.items()
                    if r["split"] == "holdout" and k not in excl)
    with open(args.audit, encoding="utf-8-sig") as f:
        audit = [r for r in csv.DictReader(f) if r["label_llm"].strip() in ("0", "1")]
    print(f"Tổng thể: {sum(sizes.values())} cặp ứng viên holdout · mẫu có nhãn: {len(audit)}")

    rng = np.random.default_rng(0)
    for spec in args.system:
        name, path = spec.split("=", 1)
        sysp = _load_p(path)
        strata: dict[str, list[tuple[int, int]]] = defaultdict(list)
        missing = 0
        for r in audit:
            key = frozenset((r["a"], r["b"]))
            rec = sysp.get(key)
            if rec is None:
                missing += 1
                pred = 0
            else:
                pred = int(rec["p"] >= args.pos_threshold)
            strata[f"{r['p_bin']}|{r['cross_source']}"].append((int(r["label_llm"]), pred))
        prec, rec_ = weighted_pr(strata, sizes)
        boots = []
        for _ in range(args.n_boot):
            bs = {s: [rows[i] for i in rng.integers(0, len(rows), len(rows))] for s, rows in strata.items()}
            boots.append(weighted_pr(bs, sizes))
        b = np.array(boots)
        raw_p = [y for rows in strata.values() for y, d in rows if d]
        raw_r = [d for rows in strata.values() for y, d in rows if y]
        print(f"\n[{name}] (p ≥ {args.pos_threshold})" + (f" — {missing} cặp mẫu không có trong hệ thống, tính là âm"
                                                          if missing else ""))
        print(f"  precision (có trọng số) {prec:.3f}  CI95 [{np.nanpercentile(b[:, 0], 2.5):.3f}, "
              f"{np.nanpercentile(b[:, 0], 97.5):.3f}]   · thô trên mẫu {np.mean(raw_p):.3f} (n={len(raw_p)})")
        print(f"  recall    (có trọng số) {rec_:.3f}  CI95 [{np.nanpercentile(b[:, 1], 2.5):.3f}, "
              f"{np.nanpercentile(b[:, 1], 97.5):.3f}]   · thô trên mẫu {np.mean(raw_r):.3f} "
              f"({int(np.sum(raw_r))}/{len(raw_r)})")


if __name__ == "__main__":
    main()
