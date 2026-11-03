"""Trang trực quan tập vàng gom cụm: kích thước cụm, dòng thời gian sự kiện lớn, bản đồ 2D, và thí nghiệm "nối cặp".

    uv run --group embed --with pyvi python -m eventrank.evaluation.gold_viz
        → data/gold_clusters/v1/truc_quan.html (mở bằng trình duyệt; chứa tiêu đề bài báo — chỉ dùng trong nhóm)

Nhãn = đề xuất của Claude sau vòng kiểm tra B + C (proposals_v2.json; nếu chưa có thì proposals.json), chưa có người duyệt. Vị trí 2D = embedding bkai fine-tune (v1, s44) chiếu bằng t-SNE
(cosine) — chỉ để nhìn, khoảng cách trên hình không phải khoảng cách thật.

Thí nghiệm "nối cặp": coi mọi cặp bài trong 48h có cosine ≥ ngưỡng là cùng sự kiện, lấy thành phần liên thông làm cụm, chấm
B-Cubed với đề xuất của Claude. Trả lời câu hỏi "sao không lấy cặp embedding làm cụm luôn": ngưỡng thấp thì bắc cầu
(A~B, B~C ⇒ A, B, C chung cụm) thành cụm khổng lồ; ngưỡng cao thì vỡ vụn.
"""
from __future__ import annotations

import json
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from eventrank.evaluation.bcubed import bcubed
from eventrank.evaluation.gold_clusters import DEFAULT_OUT, ROOT, _articles

MODEL = ROOT / "data/temp/kaggle_runs/2026-10-15_bkai-cosent-v4hard/bkai-v4-cosent-s44"
TEMPLATE = Path(__file__).with_name("gold_viz.html")
THRESHOLDS = [round(0.70 + 0.025 * k, 3) for k in range(11)]          # 0,70 → 0,95


def link_components(E: np.ndarray, times: np.ndarray, threshold: float, window_hours: float = 48) -> np.ndarray:
    """Nhãn cụm = thành phần liên thông của cạnh (cosine ≥ threshold VÀ cách nhau ≤ window_hours). E đã chuẩn hoá L2."""
    S = E @ E.T
    edge = (S >= threshold) & (np.abs(times[:, None] - times[None, :]) <= window_hours * 3600)
    parent = np.arange(len(E))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u, v in zip(*np.nonzero(np.triu(edge, 1)), strict=True):
        parent[find(u)] = find(v)
    return np.array([find(i) for i in range(len(E))])


def sweep(E: np.ndarray, times: np.ndarray, gold: dict[int, str], thresholds: list[float]) -> list[dict]:
    """B-Cubed của cách "nối cặp" ở từng ngưỡng, so với `gold` (chỉ số bài → cụm; bài loại không có trong gold)."""
    rows = []
    for th in thresholds:
        lab = link_components(E, times, th)
        pred = {i: int(lab[i]) for i in gold}
        p, r, f = bcubed(pred, gold)
        sizes = Counter(pred.values())
        rows.append({"threshold": th, "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4),
                     "n_clusters": len(sizes), "largest": max(sizes.values())})
    return rows


def _embed(arts: list[dict], cache: Path) -> np.ndarray:
    ids = [a["id"] for a in arts]
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        if list(z["ids"]) == ids:
            return z["E"]
    from pyvi import ViTokenizer
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(MODEL), device="cpu")
    text = lambda a: f"{a['title']}. {a['sapo']}".strip(" .") if a["sapo"] else a["title"]   # giống corpus.py
    E = model.encode([ViTokenizer.tokenize(unicodedata.normalize("NFC", text(a))) for a in arts],
                     batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    np.savez(cache, ids=np.array(ids), E=E)
    return E


def build(out_dir: str | Path = DEFAULT_OUT) -> Path:
    from sklearn.manifold import TSNE

    out = Path(out_dir)
    arts = _articles(out)
    src = out / "proposals_v2.json" if (out / "proposals_v2.json").exists() else out / "proposals.json"   # v2 = sau vòng kiểm tra
    proposals = json.loads(src.read_text(encoding="utf-8"))
    E = _embed(arts, out / "emb_bkai_ft.npz")
    summ: dict[str, dict] = {}                        # tóm tắt toàn văn (nếu có) để hiện khi bấm vào bài
    for f in sorted((out / "llm").glob("tom_tat_[0-9]*.json")):
        summ.update(json.loads(f.read_text(encoding="utf-8")))
    times = np.array([datetime.fromisoformat(a["t"]).timestamp() for a in arts])

    clusters = [c for p in proposals for c in p["clusters"]]
    excluded = {i for p in proposals for i in p["x"]}
    clusters.sort(key=lambda c: (-len(c["members"]), c["members"][0]))
    cid = {i: k for k, c in enumerate(clusters) for i in c["members"]}
    gold = {i: k for i, k in cid.items()}

    xy = TSNE(n_components=2, metric="cosine", init="pca", perplexity=30, random_state=0).fit_transform(E)
    xy = (xy - xy.min(0)) / (xy.max(0) - xy.min(0))

    sizes = Counter(len(c["members"]) for c in clusters)
    bins = [("1 bài", 1, 1), ("2 bài", 2, 2), ("3–5", 3, 5), ("6–10", 6, 10), ("11–20", 11, 20), ("> 20", 21, 10**9)]
    hist = [{"label": lab, "clusters": sum(v for s, v in sizes.items() if lo <= s <= hi),
             "articles": sum(s * v for s, v in sizes.items() if lo <= s <= hi)} for lab, lo, hi in bins]
    data = {
        "dataset": json.loads((out / "meta.json").read_text(encoding="utf-8"))["dataset"],
        "articles": [{"stt": a["stt"], "t": a["t"], "source": a["source"], "title": a["title"], "url": a.get("url", ""),
                      "sv": summ.get(str(a["stt"]), {}).get("su_viec", ""),
                      "tt": summ.get(str(a["stt"]), {}).get("tom_tat", "") or a.get("sapo", ""),
                      "c": cid.get(i, -1), "xy": [round(float(xy[i, 0]), 4), round(float(xy[i, 1]), 4)]}
                     for i, a in enumerate(arts)],
        "clusters": [{"name": c["name"] or arts[c["members"][0]]["title"], "members": c["members"],
                      "sources": len({arts[i]["source"] for i in c["members"]}), "low": c["confidence"] == "thấp"}
                     for c in clusters],
        "kpi": {"articles": len(arts), "clusters": len(clusters), "multi": sum(len(c["members"]) >= 2 for c in clusters),
                "multi_articles": sum(len(c["members"]) for c in clusters if len(c["members"]) >= 2),
                "excluded": len(excluded)},
        "hist": hist,
        "sweep": sweep(E, times, gold, THRESHOLDS),
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = out / "truc_quan.html"
    html.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload), encoding="utf-8")
    return html


if __name__ == "__main__":
    path = build()
    print(f"→ {path} ({path.stat().st_size / 1e6:.1f} MB)")
