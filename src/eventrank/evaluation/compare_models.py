"""So sánh mô hình embedding GỐC (zero-shot) với bản FINE-TUNE trên cùng tập đo cặp 4 mức — chạy ở máy, CPU.

    uv run --group embed --with pyvi python -m eventrank.evaluation.compare_models
    uv run --group embed --with pyvi python -m eventrank.evaluation.compare_models \\
        --model e5_zs=intfloat/multilingual-e5-base:query          # thêm mô hình (tên=đường_dẫn:tiền_xử_lý)

Mặc định so `bkai_zs` (data/models/bkai_zs = bkai-foundation-models/vietnamese-bi-encoder; chưa có thì tự tải từ
Hugging Face) với `bkai_ft` (data/models/bkai_ft_v1_s44 = v1, seed 44). Mô hình mới từ Kaggle: nhập bằng
`training/import_kaggle_run.py`, lệnh đó in sẵn `--model …` để dán vào đây. Tiền xử lý PHẢI giống lúc train: `pyvi` = NFC + tách từ (bkai), `query` = NFC + "query: " (e5),
`raw` = chỉ NFC.

Dữ liệu: `data/datasets/cap_su_kien_v4.csv` (sinh bằng gold_export), hai phần không giao nhau:
- `test` (648 cặp): cosine trung bình mỗi mức, AUC giữa hai mức liền kề, Spearman, AP (mức 3 = dương).
- `test_hard` (196 cặp "cùng nội dung, khác chữ"): AUC 3>2, AP, và ở ngưỡng F1 tốt nhất chọn trên `test`:
  recall mức 3, tỉ lệ cặp mức ≤ 2 bị gộp nhầm.
Không dùng trọng số tầng nên số khớp với notebook Kaggle (`graded`, `hard`), trừ ngưỡng: notebook chọn ngưỡng trên
audit_v1, ở đây chọn trên `test`.

Δ = mô hình sau − mô hình đầu tiên, CI 95% bằng bootstrap GHÉP CẶP (cùng mẫu lại cho cả hai; chọn lại ngưỡng mỗi lần).
Vector được lưu đệm ở data/temp/compare_models/emb_<tên>.npz — chạy lại không phải encode.
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
from pathlib import Path

import numpy as np

from eventrank.embeddings.encode import prep
from eventrank.evaluation.gold_clusters import ROOT

PAIRS = ROOT / "data/datasets/cap_su_kien_v4.csv"
CACHE = ROOT / "data/temp/compare_models"
DEFAULT_MODELS = [
    "bkai_zs=data/models/bkai_zs:pyvi",              # bản chép của bkai-foundation-models/vietnamese-bi-encoder
    "bkai_ft=data/models/bkai_ft_v1_s44:pyvi",
]
DELTA_KEYS = ["auc_3v2", "auc_2v1", "spearman", "ap", "hard_auc_3v2", "hard_ap", "recall_hard",
              "false_merge_hard"]


def parse_model(spec: str) -> dict:
    """'tên=đường_dẫn:tiền_xử_lý' → dict. Tiền xử lý bỏ trống = pyvi."""
    name, rest = spec.split("=", 1)
    path, _, prep = rest.rpartition(":") if rest.rsplit(":", 1)[-1] in ("pyvi", "query", "raw") else (rest, "", "pyvi")
    local = ROOT / path
    if not local.exists() and name == "bkai_zs":                       # máy chưa chép bản gốc → tải
        path = "bkai-foundation-models/vietnamese-bi-encoder"
    return {"name": name, "path": str(local) if local.exists() else path, "prep": prep}


def load_pairs(path: str | Path = PAIRS) -> dict[str, dict]:
    """{split: {a, b, level (np), text: {id: văn bản}}} cho test và test_hard."""
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["split"] == "train":
                continue
            s = out.setdefault(r["split"], {"a": [], "b": [], "level": [], "text": {}})
            s["a"].append(r["a"])
            s["b"].append(r["b"])
            s["level"].append(int(r["level"]))
            s["text"][r["a"]], s["text"][r["b"]] = r["text_a"], r["text_b"]
    for s in out.values():
        s["level"] = np.array(s["level"])
    return out


def embed(model: dict, texts: dict[str, str], cache: Path = CACHE) -> dict[str, np.ndarray]:
    ids = sorted(texts)
    f = cache / f"emb_{model['name']}.npz"
    if f.exists():
        z = np.load(f, allow_pickle=True)
        if list(z["ids"]) == ids and str(z["path"]) == model["path"]:
            return dict(zip(ids, z["E"]))
    from sentence_transformers import SentenceTransformer

    print(f"  encode {len(ids)} bài bằng {model['path']} ({model['prep']})…", flush=True)
    st = SentenceTransformer(model["path"], device="cpu")
    st.max_seq_length = 256                                          # giống lúc fine-tune
    E = st.encode([prep(texts[i], model["prep"]) for i in ids], batch_size=16,
                  normalize_embeddings=True, show_progress_bar=True)
    del st
    gc.collect()                                                     # máy 7,6 GB: không giữ 2 mô hình cùng lúc
    cache.mkdir(parents=True, exist_ok=True)
    np.savez(f, ids=np.array(ids), E=E, path=model["path"])
    return dict(zip(ids, E))


def cosines(E: dict[str, np.ndarray], split: dict) -> np.ndarray:
    return np.array([float(E[a] @ E[b]) for a, b in zip(split["a"], split["b"])])


# --- Chỉ số (thuần numpy, có test) ---

def auc(s: np.ndarray, L: np.ndarray, hi: int, lo: int) -> float:
    """Xác suất một cặp mức hi có cosine lớn hơn một cặp mức lo (hoà tính 0,5)."""
    a, b = s[L == hi], s[L == lo]
    if not len(a) or not len(b):
        return float("nan")
    return float((a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean())


def average_precision(s: np.ndarray, y: np.ndarray) -> float:
    o = np.argsort(-s, kind="stable")
    yo = y[o]
    if not yo.sum():
        return float("nan")
    return float(np.sum(np.cumsum(yo) / np.arange(1, len(yo) + 1) * yo) / yo.sum())


def best_threshold(s: np.ndarray, y: np.ndarray) -> float:
    """Ngưỡng cho F1 cao nhất (dương khi s ≥ ngưỡng); hoà thì lấy ngưỡng nhỏ nhất — giống notebook."""
    o = np.argsort(-s, kind="stable")
    so, yo = s[o], y[o]
    f1 = 2 * np.cumsum(yo) / (np.arange(1, len(s) + 1) + y.sum())
    f1[np.r_[so[1:] == so[:-1], False]] = -1
    return float(so[len(f1) - 1 - np.argmax(f1[::-1])])


def metrics(st: np.ndarray, Lt: np.ndarray, sh: np.ndarray, Lh: np.ndarray) -> dict:
    from scipy.stats import spearmanr

    th = best_threshold(st, (Lt == 3).astype(int))
    pos, neg = Lh == 3, Lh <= 2
    return dict(
        **{f"mean_cos_level{k}": float(st[Lt == k].mean()) for k in (3, 2, 1, 0) if (Lt == k).any()},
        auc_3v2=auc(st, Lt, 3, 2), auc_2v1=auc(st, Lt, 2, 1), auc_1v0=auc(st, Lt, 1, 0),
        spearman=float(spearmanr(st, Lt).statistic), ap=average_precision(st, (Lt == 3).astype(int)),
        threshold=th, hard_auc_3v2=auc(sh, Lh, 3, 2), hard_ap=average_precision(sh, pos.astype(int)),
        recall_hard=float((sh[pos] >= th).mean()) if pos.any() else float("nan"),
        false_merge_hard=float((sh[neg] >= th).mean()) if neg.any() else float("nan"),
    )


def paired_bootstrap(sa: tuple, sb: tuple, Lt: np.ndarray, Lh: np.ndarray, n_boot: int = 1000,
                     seed: int = 0) -> dict:
    """sa, sb = (cosine test, cosine test_hard) của mô hình A, B. Trả Δ = B − A với CI 95%."""
    rng = np.random.default_rng(seed)
    pick = lambda m: np.array([m[k] for k in DELTA_KEYS])
    point = pick(metrics(sb[0], Lt, sb[1], Lh)) - pick(metrics(sa[0], Lt, sa[1], Lh))
    deltas = []
    for _ in range(n_boot):
        it, ih = rng.integers(0, len(Lt), len(Lt)), rng.integers(0, len(Lh), len(Lh))
        ma = metrics(sa[0][it], Lt[it], sa[1][ih], Lh[ih])
        mb = metrics(sb[0][it], Lt[it], sb[1][ih], Lh[ih])
        deltas.append(pick(mb) - pick(ma))
    deltas = np.array(deltas)
    return {k: {"delta": float(point[j]), "ci95": [float(np.nanpercentile(deltas[:, j], 2.5)),
                                                 float(np.nanpercentile(deltas[:, j], 97.5))],
                    "p_le_0": float(np.mean(deltas[:, j] <= 0))}
            for j, k in enumerate(DELTA_KEYS)}


def run(models: list[dict], pairs: str | Path = PAIRS, n_boot: int = 1000) -> dict:
    data = load_pairs(pairs)
    test, hard = data["test"], data["test_hard"]
    texts = {**test["text"], **hard["text"]}
    scores, res = {}, {}
    for m in models:
        E = embed(m, texts)
        scores[m["name"]] = (cosines(E, test), cosines(E, hard))
        res[m["name"]] = metrics(scores[m["name"]][0], test["level"], scores[m["name"]][1], hard["level"])
    base = models[0]["name"]
    cmp = {f"{m['name']} vs {base}": paired_bootstrap(scores[base], scores[m["name"]], test["level"],
                                                      hard["level"], n_boot)
           for m in models[1:]}
    return {"models": models, "n_test": len(test["level"]), "n_hard": len(hard["level"]), "metrics": res, "compare": cmp,
                "n_boot": n_boot}


def show(out: dict) -> None:
    rows = [("mean_cos_level3", "cos TB mức 3"), ("mean_cos_level2", "cos TB mức 2"), ("mean_cos_level1", "cos TB mức 1"),
            ("mean_cos_level0", "cos TB mức 0"), ("auc_3v2", "AUC 3>2"), ("auc_2v1", "AUC 2>1"), ("auc_1v0", "AUC 1>0"),
            ("spearman", "Spearman"), ("ap", "AP (mức 3)"), ("threshold", "ngưỡng F1"),
            ("hard_auc_3v2", "khác chữ AUC 3>2"), ("hard_ap", "khác chữ AP"), ("recall_hard", "khác chữ recall"),
            ("false_merge_hard", "khác chữ gộp nhầm")]
    names = list(out["metrics"])
    print(f"\ntest {out['n_test']} cặp · test_hard {out['n_hard']} cặp")
    print(f"{'chỉ số':20s}" + "".join(f"{n:>12s}" for n in names))
    for k, label in rows:
        print(f"{label:20s}" + "".join(f"{out['metrics'][n][k]:12.3f}" for n in names))
    for title, c in out["compare"].items():
        print(f"\nΔ {title} (CI 95% bootstrap ghép cặp, {out['n_boot']} lần; CI không chứa 0 → khác thật)")
        for k, v in c.items():
            flag = " *" if v["ci95"][0] > 0 or v["ci95"][1] < 0 else ""
            print(f"  {k:18s}{v['delta']:+.3f}  [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}]{flag}")
    print("\n(gộp nhầm, ngưỡng: thấp hơn không hẳn tốt hơn — thang cosine mỗi mô hình khác nhau)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", action="append", default=[],
                    help="thêm mô hình: tên=đường_dẫn:pyvi|query|raw; lặp lại được")
    ap.add_argument("--no-default", action="store_true",
                    help="bỏ bkai_zs, bkai_ft mặc định; mô hình --model ĐẦU TIÊN là mốc so")
    ap.add_argument("--pairs", default=str(PAIRS))
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", default=str(CACHE / "ket_qua.json"))
    a = ap.parse_args()
    specs = ([] if a.no_default else DEFAULT_MODELS) + a.model
    out = run([parse_model(s) for s in specs], a.pairs, a.n_boot)
    show(out)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
