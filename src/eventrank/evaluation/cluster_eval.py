"""Chấm gom cụm sự kiện trên tập vàng 14–15/09/2026 — chạy ở máy, CPU (bản local của training/cluster_eval_kaggle.ipynb).

    uv run --group embed --with pyvi python -m eventrank.evaluation.cluster_eval
        → data/temp/cluster_eval/ket_qua.json (+ loi_*.csv, du_doan_*.csv)

Thuật toán ở eventrank.clustering.algorithms (dùng chung với pipeline gom cụm). Mỗi mô hình embedding (+ hai baseline không học: `tfidf`, `tfidf_ent` = TF-IDF + thực thể NER có trọng số IDF) × hai
thuật toán:
- `single_pass`: duyệt bài theo thời gian, bài vào cụm có cosine TRUNG BÌNH với các thành viên cao nhất nếu ≥ ngưỡng
  (cụm không có bài mới quá 48h thì "nguội"), không thì mở cụm mới — giống cách gán nhanh khi chạy thật.
- `agglo`: agglomerative average-linkage trên cả cửa sổ, cặp cách nhau > 48h coi như rất xa, cắt cây ở ngưỡng.

Ngưỡng chọn trên ngày 14/09 (B-Cubed F1 cao nhất), báo cáo trên ngày 15/09. CI 95% bằng bootstrap lấy mẫu lại CỤM VÀNG
(bài cùng sự kiện không độc lập), so hai cấu hình bằng bootstrap ghép cặp. Bài `x` (loại) không chấm.
Vector lưu đệm ở data/temp/cluster_eval/emb_<tên>.npz — chạy lại không phải encode.
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from eventrank.clustering.algorithms import WINDOW_HOURS, agglo_cut, agglo_tree, single_pass
from eventrank.embeddings.encode import prep
from eventrank.evaluation.compare_models import parse_model
from eventrank.evaluation.gold_clusters import DEFAULT_OUT, ROOT

CACHE = ROOT / "data/temp/cluster_eval"
GOLD_NER = ROOT / "data/lake/gold/gold_data.jsonl"
DEFAULT_MODELS = [
    "bkai_zs=data/models/bkai_zs:pyvi",
    "bkai_ft=data/models/bkai_ft_v1_s44:pyvi",
    "bkai_v2_s42=data/models/bkai-v4-cosent-s42_2026-10-30:pyvi",
    "bkai_v2_s43=data/models/bkai-v4-cosent-s43_2026-10-30:pyvi",
    "bkai_v2_s44=data/models/bkai-v4-cosent-s44_2026-10-30:pyvi",
    "e5_zs=intfloat/multilingual-e5-base:query",
    "e5_v2_s42=data/models/e5-v4-cosent-s42_2026-10-30:query",
    "e5_v2_s43=data/models/e5-v4-cosent-s43_2026-10-30:query",
    "e5_v2_s44=data/models/e5-v4-cosent-s44_2026-10-30:query",
]
ALGOS = ["single_pass", "agglo"]
GRID = [round(0.05 + 0.01 * k, 2) for k in range(91)]                 # 0,05 → 0,95


def text(a: dict) -> str:
    return f"{a['title']}. {a['sapo']}".strip(" .") if a.get("sapo") else a["title"]


def load_gold(gold_dir: str | Path = DEFAULT_OUT) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """(bài theo stt, article_id → cụm vàng, cụm → độ tin). Cụm `x` = bài loại."""
    gold_dir = Path(gold_dir)
    with open(gold_dir / "articles.jsonl", encoding="utf-8") as f:
        arts = [json.loads(line) for line in f]
    with open(gold_dir / "gold_clusters_v2.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return arts, {r["article_id"]: r["cluster_id"] for r in rows}, {r["cluster_id"]: r["confidence"] for r in rows}


def tfidf(arts: list[dict]):
    """Từ đơn + cặp hai từ trên văn bản thô, chuẩn hoá L2 (ma trận thưa)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    X = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, token_pattern=r"(?u)\b\w+\b")
    return X.fit_transform([prep(text(a), "raw") for a in arts]).astype(np.float32)


def entity_vectors(arts: list[dict], ner_path: str | Path = GOLD_NER):
    """Mỗi bài = vector thực thể NER đã chuẩn hoá (weak_labels.entities), trọng số = độ nổi bật × IDF trong cửa sổ."""
    from scipy import sparse

    from eventrank.weak_labels.entities import EntityNormalizer, article_entities, load_aliases

    want = {a["id"] for a in arts}
    ner = {}
    with open(ner_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["article_id"] in want:
                ner[r["article_id"]] = r["entities"]
    norm = EntityNormalizer(load_aliases(ROOT / "configs/entity_aliases.yaml"))
    bags = [{k: e.salience for k, e in article_entities({**a, "entities": ner.get(a["id"], [])}, norm).items()}
            for a in arts]
    vocab = {k: j for j, k in enumerate(sorted({k for b in bags for k in b}))}
    df = Counter(k for b in bags for k in b)
    idf = {k: np.log(len(arts) / df[k]) for k in df}
    rows, cols, vals = [], [], []
    for i, b in enumerate(bags):
        for k, sal in b.items():
            rows.append(i)
            cols.append(vocab[k])
            vals.append(sal * idf[k])
    X = sparse.csr_matrix((vals, (rows, cols)), shape=(len(arts), len(vocab)), dtype=np.float32)
    n = np.sqrt(np.asarray(X.multiply(X).sum(1))).ravel()
    return sparse.diags(1 / np.where(n > 0, n, 1)) @ X


def embed(model: dict, arts: list[dict], cache: Path = CACHE):
    """Ma trận vector (đã chuẩn hoá L2) theo thứ tự `arts`. `tfidf_ent`: nối [TF-IDF, thực thể] mỗi phần nhân √0,5
    → cosine = trung bình cosine chữ và cosine thực thể (trọng số định trước, không chỉnh)."""
    from scipy import sparse

    ids = [a["id"] for a in arts]
    if model["path"] == "tfidf":
        return tfidf(arts)
    if model["path"] == "tfidf_ent":
        return sparse.hstack([tfidf(arts) * np.sqrt(0.5), entity_vectors(arts) * np.sqrt(0.5)]).tocsr()
    f = cache / f"emb_{model['name']}.npz"
    if f.exists():
        z = np.load(f, allow_pickle=True)
        if list(z["ids"]) == ids and str(z["path"]) == model["path"]:
            return z["E"]
    from sentence_transformers import SentenceTransformer

    print(f"  encode {len(ids)} bài bằng {model['path']} ({model['prep']})…", flush=True)
    st = SentenceTransformer(model["path"], device="cpu")
    st.max_seq_length = 256
    E = st.encode([prep(text(a), model["prep"]) for a in arts], batch_size=16, normalize_embeddings=True,
                  show_progress_bar=False).astype(np.float32)
    del st
    gc.collect()                                                     # máy 7,6 GB: không giữ 2 mô hình cùng lúc
    cache.mkdir(parents=True, exist_ok=True)
    np.savez(f, ids=np.array(ids), E=E, path=model["path"])
    return E


def similarity(E) -> np.ndarray:
    S = E @ E.T
    return np.asarray(S.toarray() if hasattr(S, "toarray") else S, dtype=np.float32)


# --- Chỉ số ---

def per_item(pred: np.ndarray, gold: np.ndarray, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Precision, recall B-Cubed của từng bài trong idx (chỉ tính trong idx)."""
    p, g = pred[idx], gold[idx]
    n_p, n_g, n_pg = Counter(p), Counter(g), Counter(zip(p, g, strict=True))
    P = np.array([n_pg[a, b] / n_p[a] for a, b in zip(p, g, strict=True)])
    R = np.array([n_pg[a, b] / n_g[b] for a, b in zip(p, g, strict=True)])
    return P, R


def f1(P: np.ndarray, R: np.ndarray, w: np.ndarray | None = None) -> float:
    p, r = np.average(P, weights=w), np.average(R, weights=w)
    return float(2 * p * r / (p + r)) if p + r else 0.0


def boot_weights(gold: np.ndarray, idx: np.ndarray, n_boot: int, seed: int = 0) -> np.ndarray:
    """n_boot × len(idx): mỗi lần rút có hoàn lại các cụm vàng, trọng số mỗi bài = số lần cụm của nó được rút."""
    rng = np.random.default_rng(seed)
    cl = sorted(set(gold[idx]))
    pos = {c: k for k, c in enumerate(cl)}
    item_cl = np.array([pos[c] for c in gold[idx]])
    counts = np.stack([np.bincount(d, minlength=len(cl)) for d in rng.integers(0, len(cl), (n_boot, len(cl)))])
    return counts[:, item_cl]


def purity(a: np.ndarray, b: np.ndarray) -> float:
    """Tỉ lệ bài thuộc nhóm-b chiếm đa số trong cụm-a của nó. purity(pred, gold); đảo lại = inverse purity."""
    return sum(Counter(b[a == c]).most_common(1)[0][1] for c in set(a)) / len(a)


def score(pred: np.ndarray, gold: np.ndarray, idx: np.ndarray, W: np.ndarray | None = None) -> dict:
    P, R = per_item(pred, gold, idx)
    out = {"precision": float(P.mean()), "recall": float(R.mean()), "f1": f1(P, R), "n": len(idx),
           "n_pred_clusters": len(set(pred[idx]))}
    if W is not None:                                                # chỉ số phụ: chỉ tính ở cấu hình báo cáo
        from sklearn.metrics import adjusted_mutual_info_score

        p, g = pred[idx].astype(str), gold[idx].astype(str)
        out.update(ami=float(adjusted_mutual_info_score(g, p)), purity=purity(p, g), inverse_purity=purity(g, p))
    if W is not None:
        boot = np.array([f1(P, R, w) for w in W])
        out["f1_ci95"] = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
        out["_boot"] = boot
    return out


def delta(a: dict, b: dict) -> dict:
    """b − a, CI 95% từ bootstrap ghép cặp (a, b chấm cùng trọng số W)."""
    d = b["_boot"] - a["_boot"]
    return {"delta": b["f1"] - a["f1"], "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "p_le_0": float(np.mean(d <= 0))}


def lexical_tiers(St: np.ndarray, gold: np.ndarray, idx: np.ndarray) -> dict[str, str]:
    """Cụm vàng ≥ 2 bài → 'thấp' | 'vừa' | 'cao' theo cosine TF-IDF trung bình giữa các bài (chia ba phần bằng nhau)."""
    lex = {}
    for c in set(gold[idx]):
        mem = [i for i in idx if gold[i] == c]
        if len(mem) >= 2:
            sub = St[np.ix_(mem, mem)]
            lex[c] = float(sub[np.triu_indices(len(mem), 1)].mean())
    cut = np.quantile(list(lex.values()), [1 / 3, 2 / 3])
    return {c: ("thấp" if v < cut[0] else "vừa" if v < cut[1] else "cao") for c, v in lex.items()}


def errors(pred: np.ndarray, gold: np.ndarray, idx: np.ndarray, arts: list[dict]) -> list[dict]:
    """Cụm dự đoán chứa ≥ 2 sự kiện vàng (gộp nhầm) và sự kiện vàng bị chia ≥ 2 cụm (tách nhầm), lớn trước."""
    rows = []
    for c in sorted(set(pred[idx])):
        mem = [i for i in idx if pred[i] == c]
        if len(set(gold[mem])) >= 2:
            rows.append({"loai": "gop_nham", "so_bai": len(mem), "so_nhom": len(set(gold[mem])),
                         "bai": [{"stt": arts[i]["stt"], "nhom": str(gold[i]), "source": arts[i]["source"],
                                  "t": arts[i]["t"][5:16], "title": arts[i]["title"]} for i in mem]})
    for c in sorted(set(gold[idx])):
        mem = [i for i in idx if gold[i] == c]
        if len(set(pred[mem])) >= 2:
            rows.append({"loai": "tach_nham", "so_bai": len(mem), "so_nhom": len(set(pred[mem])),
                         "bai": [{"stt": arts[i]["stt"], "nhom": int(pred[i]), "source": arts[i]["source"],
                                  "t": arts[i]["t"][5:16], "title": arts[i]["title"]} for i in mem]})
    return sorted(rows, key=lambda r: -r["so_bai"])


def run(models: list[dict], gold_dir: str | Path = DEFAULT_OUT, n_boot: int = 1000,
        tune_day: str = "2026-09-14", test_day: str = "2026-09-15") -> dict:
    arts, gold_of, conf_of = load_gold(gold_dir)
    times = np.array([datetime.fromisoformat(a["t"]).timestamp() for a in arts])
    day = np.array([a["t"][:10] for a in arts])
    gold = np.array([gold_of[a["id"]] for a in arts], dtype=object)
    keep = gold != "x"
    TUNE, TEST = np.where(keep & (day == tune_day))[0], np.where(keep & (day == test_day))[0]
    W = boot_weights(gold, TEST, n_boot)

    curves, best, res, preds, sims = {}, {}, {}, {}, {}
    for m in models:
        S = similarity(embed(m, arts))
        sims[m["name"]] = S
        off = S[np.triu_indices(len(S), 1)]
        print(f"{m['name']:12s} cosine trung vị {np.median(off):.3f} · p99 {np.percentile(off, 99):.3f}", flush=True)
        Z = agglo_tree(S, times)
        for algo in ALGOS:
            labs = [single_pass(S, times, th) if algo == "single_pass" else agglo_cut(Z, th) for th in GRID]
            key = f"{m['name']}|{algo}"
            curves[key] = {"tune": [score(lab, gold, TUNE)["f1"] for lab in labs],
                           "test": [score(lab, gold, TEST)["f1"] for lab in labs]}
            k = int(np.argmax(curves[key]["tune"]))
            best[key], preds[key] = GRID[k], labs[k]
            res[key] = score(labs[k], gold, TEST, W)
            r = res[key]
            print(f"  {algo:11s} ngưỡng {GRID[k]:.2f} · F1 14/09 {curves[key]['tune'][k]:.3f} · F1 15/09 {r['f1']:.3f} "
                  f"[{r['f1_ci95'][0]:.3f}, {r['f1_ci95'][1]:.3f}]", flush=True)
    trivial = score(np.arange(len(arts)), gold, TEST, W)

    St = sims.get("tfidf")
    tier = lexical_tiers(St, gold, TEST) if St is not None else {}
    gold_split = gold.copy()                                         # độ nhạy: tách cụm "không chắc" thành từng bài
    for i in range(len(arts)):
        if conf_of.get(gold[i]) == "thấp":
            gold_split[i] = f"{gold[i]}#{i}"
    analysis = {}
    for key, pred in preds.items():
        _, R = per_item(pred, gold, TEST)
        row = {f"recall_{t}": float(R[np.array([tier.get(gold[i]) == t for i in TEST])].mean())
               for t in ("thấp", "vừa", "cao") if tier}
        row["f1_tach_khong_chac"] = score(pred, gold_split, TEST)["f1"]
        sizes = Counter(pred[TEST])
        row["largest"] = max(sizes.values())
        row["n_multi"] = sum(v >= 2 for v in sizes.values())
        analysis[key] = row

    names = [m["name"] for m in models]
    pairs = []
    for algo in ALGOS:
        for a, b in [("tfidf", "tfidf_ent"), ("bkai_zs", "bkai_ft"), ("bkai_zs", "bkai_v2_s42"), ("e5_zs", "e5_v2_s43"), ("tfidf", "bkai_zs"),
                     ("tfidf", "e5_zs"), ("tfidf", "bkai_v2_s42"), ("tfidf", "e5_v2_s43"),
                     ("tfidf_ent", "bkai_v2_s42"), ("tfidf_ent", "e5_v2_s43"), ("bkai_ft", "bkai_v2_s42"),
                     ("bkai_v2_s42", "e5_v2_s43")]:
            if a in names and b in names:
                pairs.append({"algo": algo, "a": a, "b": b, **delta(res[f"{a}|{algo}"], res[f"{b}|{algo}"])})
    for n in names:
        pairs.append({"algo": "agglo − single_pass", "a": n, "b": n,
                      **delta(res[f"{n}|single_pass"], res[f"{n}|agglo"])})

    gold_sizes = Counter(gold[TEST])
    return {
        "models": models, "algos": ALGOS, "grid": GRID, "window_hours": WINDOW_HOURS, "n_boot": n_boot,
        "tune_day": tune_day, "test_day": test_day,
        "data": {"n_articles": len(arts), "n_excluded": int((~keep).sum()), "n_tune": len(TUNE), "n_test": len(TEST),
                 "test_gold_clusters": len(gold_sizes), "test_gold_multi": sum(v >= 2 for v in gold_sizes.values()),
                 "test_gold_size_hist": dict(Counter(min(v, 10) for v in gold_sizes.values()))},
        "thresholds": best, "curves": curves,
        "test": {k: {kk: vv for kk, vv in r.items() if kk != "_boot"} for k, r in res.items()},
        "trivial": {k: v for k, v in trivial.items() if k != "_boot"},
        "pairs": pairs, "analysis": analysis, "tiers": dict(Counter(tier.values())),
        "_preds": preds, "_gold": gold, "_test": TEST, "_arts": arts,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", action="append", default=[], help="thêm mô hình: tên=đường_dẫn:pyvi|query|raw")
    ap.add_argument("--no-default", action="store_true", help="chỉ chấm TF-IDF + các --model")
    ap.add_argument("--gold-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--errors-for", action="append", default=[],
                    help="ghi lỗi gộp/tách nhầm cho cấu hình tên|thuật_toán (mặc định: cấu hình tốt nhất + TF-IDF)")
    ap.add_argument("--out-dir", default=str(CACHE))
    a = ap.parse_args()
    specs = ([] if a.no_default else DEFAULT_MODELS) + a.model
    models = [{"name": "tfidf", "path": "tfidf", "prep": "raw"},
              {"name": "tfidf_ent", "path": "tfidf_ent", "prep": "raw"}] + [parse_model(s) for s in specs]
    out = run(models, a.gold_dir, a.n_boot)

    best_key = max(out["test"], key=lambda k: out["test"][k]["f1"])
    keys = a.errors_for or list(dict.fromkeys([best_key, f"tfidf|{best_key.split('|')[1]}"]))
    out["errors"] = {k: errors(out["_preds"][k], out["_gold"], out["_test"], out["_arts"]) for k in keys}
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, pred in out["_preds"].items():
        with open(out_dir / f"du_doan_{k.replace('|', '_')}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["article_id", "stt", "published_at", "pred_cluster", "gold_cluster", "title"])
            for i, art in enumerate(out["_arts"]):
                w.writerow([art["id"], art["stt"], art["t"], int(pred[i]), out["_gold"][i], art["title"]])
    for k in list(out):
        if k.startswith("_"):
            del out[k]
    (out_dir / "ket_qua.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"tốt nhất: {best_key} · → {out_dir / 'ket_qua.json'}")


if __name__ == "__main__":
    main()
