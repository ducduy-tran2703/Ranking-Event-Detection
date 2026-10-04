"""So nhãn người gán với nhãn LLM trên tập audit: Cohen's κ (kèm CI bootstrap) và danh sách cặp lệch nhau.

    uv run python -m eventrank.weak_labels.agreement
    uv run python -m eventrank.weak_labels.agreement --human data/weak_labels/v1/human_label_100.csv

Cặp có ô `label_human` để trống hoặc ghi "?" bị bỏ qua.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import numpy as np


def cohen_kappa(a: list[int], b: list[int]) -> float:
    a, b = np.asarray(a), np.asarray(b)
    po = float((a == b).mean())
    pe = sum(float((a == c).mean()) * float((b == c).mean()) for c in (0, 1))
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def _read(path: str | Path) -> dict[str, dict]:
    with open(path, encoding="utf-8-sig") as f:
        return {r["pair_no"]: r for r in csv.DictReader(f)}


def _label(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v in ("0", "1") else None


def compare(human_path: str | Path, llm_path: str | Path, n_boot: int = 2000, seed: int = 0) -> dict:
    human, llm = _read(human_path), _read(llm_path)
    pairs = []
    for no, h in human.items():
        y_h = _label(h.get("label_human"))
        y_l = _label(llm.get(no, {}).get("label_llm"))
        if y_h is not None and y_l is not None:
            pairs.append((no, y_h, y_l))
    if not pairs:
        return {"n": 0, "agree": 0, "kappa": float("nan"), "ci": (float("nan"),) * 2,
                "confusion": {}, "disagreements": []}
    h = np.array([p[1] for p in pairs])
    m = np.array([p[2] for p in pairs])
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(pairs), len(pairs))
        boots.append(cohen_kappa(h[idx], m[idx]))
    return {
        "n": len(pairs),
        "agree": int((h == m).sum()),
        "kappa": cohen_kappa(h, m),
        "ci": (float(np.nanpercentile(boots, 2.5)), float(np.nanpercentile(boots, 97.5))),
        "confusion": dict(Counter(f"người={a}/LLM={b}" for a, b in zip(h, m))),
        "disagreements": [{**llm[no], "label_human": y_h, "ghi_chu": human[no].get("ghi_chu", "")}
                          for no, y_h, y_l in pairs if y_h != y_l],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--human", default="data/weak_labels/v1/human_label_100.csv")
    ap.add_argument("--llm", default="data/weak_labels/v1/audit_labeled_llm.csv")
    args = ap.parse_args(argv)
    res = compare(args.human, args.llm)
    if res["n"] == 0:
        print(f"Chưa có cặp nào được gán trong {args.human} (cột label_human đang trống).")
        return
    print(f"Số cặp so được: {res['n']}  ·  trùng nhau: {res['agree']} ({res['agree'] / res['n']:.0%})")
    print(f"Cohen's κ = {res['kappa']:.3f}   CI95 [{res['ci'][0]:.3f}, {res['ci'][1]:.3f}]")
    print("Bảng nhầm lẫn:", res["confusion"])
    print("Đọc κ: < 0,4 kém · 0,4–0,6 vừa · 0,6–0,8 tốt · > 0,8 rất tốt")
    for d in res["disagreements"]:
        print(f"\n#{d['pair_no']}  người={d['label_human']}  LLM={d['label_llm']} "
              f"({d.get('llm_confidence', '')})  p_pipeline={d.get('p', '')}")
        print(f"  A [{d.get('source_a', '')}] {d.get('title_a', '')}")
        print(f"  B [{d.get('source_b', '')}] {d.get('title_b', '')}")
        print(f"  lý do LLM: {d.get('llm_reason', '')}")
        if d.get("ghi_chu"):
            print(f"  ghi chú của người: {d['ghi_chu']}")


if __name__ == "__main__":
    main()
