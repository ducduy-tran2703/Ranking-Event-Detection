"""Tập vàng gom cụm do NGƯỜI gán: sinh công cụ gán, gộp nhãn, đo đồng thuận người–người.

    # 1) Sinh công cụ: một file HTML tự chứa (dữ liệu nhúng sẵn) — gửi file cho người gán, mở bằng Chrome/Edge/Firefox
    uv run python -m eventrank.evaluation.gold_clusters build --start 2026-09-14 --end 2026-09-16
        → data/gold_clusters/v1/cong_cu_gan.html + articles.jsonl + meta.json

    # 2) Gán thử: 2 người gán ĐỘC LẬP cùng một đoạn (vd. STT 1–100), xuất CSV, rồi đo đồng thuận (cổng ≥ 0,7)
    uv run python -m eventrank.evaluation.gold_clusters agree nguoiA.csv nguoiB.csv

    # 3) Gán thật theo đoạn thời gian liên tiếp, rồi gộp mọi file CSV thành tập vàng
    uv run python -m eventrank.evaluation.gold_clusters merge A.csv B.csv C.csv D.csv
        → data/gold_clusters/v1/gold_clusters.csv

Cách gán (theo thứ tự thời gian đăng): mỗi bài trả lời "cùng sự kiện với cụm nào đã có, hay là sự kiện mới?".
CSV lưu mỗi bài một dòng, `link_to` là:
    article_id của một bài TRƯỚC cùng sự kiện  → cùng cụm với bài đó
    rỗng                                       → mở sự kiện mới
    x                                          → loại khỏi gom cụm (bài tổng hợp nhiều tin, không hiểu được — Gói 1)
Cụm = thành phần liên thông của các liên kết. Nhờ vậy người gán đoạn sau nối được vào cụm của người gán đoạn trước.

Gợi ý cụm trong công cụ lấy từ TF-IDF tiêu đề + sapo, KHÔNG từ mô hình embedding đang được chấm — người gán hay theo
gợi ý, gợi ý bằng mô hình sẽ kéo đáp án về phía mô hình đó. Định nghĩa sự kiện: docs/tong-hop.md mục 4.8 (mức 3).
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from eventrank.evaluation.bcubed import bcubed

ROOT = Path(__file__).resolve().parents[3]                 # gốc repo → lệnh chạy được từ bất kỳ thư mục nào
DEFAULT_OUT = ROOT / "data/gold_clusters/v1"
DEFAULT_SILVER = str(ROOT / "data/lake/silver/*/*.jsonl")
TEMPLATE = Path(__file__).with_name("gold_clusters.html")
EXCLUDED = "x"
_SPACE = re.compile(r"\s+")


BODY_CHARS = 1500                 # đoạn đầu nội dung hiện cho người gán (tiêu đề + sapo thường không đủ để phân biệt)


def _clean(s: str | None) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFC", s or "")).strip()


def _excerpt(text: str | None, limit: int = BODY_CHARS) -> str:
    """Đoạn đầu nội dung: giữ xuống đoạn, gộp khoảng trắng, cắt ở cuối câu gần giới hạn nhất."""
    paras = [p for p in (_clean(x) for x in re.split(r"\n+", text or "")) if p]
    body = "\n".join(paras)
    if len(body) <= limit:
        return body
    cut = body.rfind(". ", 0, limit)
    return body[: cut + 1 if cut > limit // 2 else limit].rstrip() + "…"


def load_window(silver_glob: str, start: str, end: str) -> list[dict]:
    """Bài có published_at trong [start, end) (so theo ngày giờ địa phương trong chuỗi), sắp theo thời gian, bỏ trùng id."""
    seen: dict[str, dict] = {}
    for path in sorted(glob.glob(silver_glob)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                a = json.loads(line)
                t = a.get("published_at") or ""
                if not (start <= t[:10] < end) or a["article_id"] in seen:
                    continue
                seen[a["article_id"]] = {
                    "id": a["article_id"], "t": t, "source": (a.get("source") or "").lower(),
                    "category": _clean(a.get("category")), "title": _clean(a.get("title")),
                    "sapo": _clean(a.get("sapo")), "body": _excerpt(a.get("content_text")),
                    "url": a.get("url") or ""}
    return sorted(seen.values(), key=lambda a: (datetime.fromisoformat(a["t"]), a["id"]))


def suggest(arts: list[dict], k: int = 12, window_hours: float = 48,
            min_sim: float = 0.05, terms: int = 0) -> list[list[tuple]]:
    """Với mỗi bài i: tối đa k bài TRƯỚC nó (≤ window_hours) giống nhất theo TF-IDF tiêu đề + sapo, giảm dần.

    Độ giống = cosine TF-IDF (từ đơn + cặp hai từ, tf log, chuẩn hoá L2): đo TRÙNG CHỮ, không đo nghĩa. terms > 0 →
    mỗi gợi ý kèm tối đa `terms` từ chung đóng góp nhiều nhất vào cosine (giải thích vì sao hai bài "giống"), bỏ từ có
    trong > 3% số bài; danh sách rỗng = hai bài chỉ trùng từ phổ biến.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    if not arts:
        return []
    texts = [f"{a['title']}. {a['sapo']}" for a in arts]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, token_pattern=r"(?u)\b\w+\b")
    X = vec.fit_transform(texts).tocsr()
    vocab = vec.get_feature_names_out()
    S = (X @ X.T).toarray()
    times = [datetime.fromisoformat(a["t"]) for a in arts]
    win = timedelta(hours=window_hours)
    df = np.bincount(X.indices, minlength=len(vocab))
    common = df > max(3, 0.03 * len(arts))          # "của", "với"… góp vào cosine nhưng không giải thích được gì
    common_words = {w for w, c in zip(vocab, common, strict=True) if c and " " not in w}
    noise = [bool(c or (" " in w and set(w.split()) & common_words)) for w, c in zip(vocab, common, strict=True)]

    def shared(i: int, j: int) -> list[str]:
        contrib = X[i].multiply(X[j]).tocoo()
        picked: list[str] = []
        for f in contrib.col[np.argsort(-contrib.data)]:
            w = str(vocab[f])
            if noise[f]:                                # từ phổ biến, hoặc cặp từ dính từ phổ biến ("gọi của")
                continue
            if not any(w in p or p in w for p in picked):       # bỏ "kuwait" khi đã có "thắng kuwait" và ngược lại
                picked.append(w)
            if len(picked) == terms:
                break
        return picked

    out = []
    for i in range(len(arts)):
        cand = [j for j in range(i) if times[i] - times[j] <= win and S[i, j] >= min_sim]
        cand.sort(key=lambda j: -S[i, j])
        out.append([(j, round(float(S[i, j]), 3), shared(i, j)) if terms else (j, round(float(S[i, j]), 3))
                    for j in cand[:k]])
    return out


def build(silver_glob: str, start: str, end: str, out_dir: str | Path = DEFAULT_OUT, k: int = 12) -> Path:
    """Sinh công cụ gán (một file HTML tự chứa) + danh sách bài + meta cho `merge`/`agree`.

    Có `<out_dir>/llm/tom_tat_*.json` ({STT: {su_viec, tom_tat, dang_bai}}, Claude tóm tắt TỪNG bài độc lập, không nói
    bài nào cùng sự kiện) → gắn vào bài để người gán đọc nhanh. Chỉ nằm trong HTML, không vào articles.jsonl.
    """
    arts = load_window(silver_glob, start, end)
    if not arts:
        raise ValueError(f"không có bài nào trong [{start}, {end}) ở {silver_glob}")
    digest = hashlib.sha1("".join(a["id"] for a in arts).encode()).hexdigest()[:8]
    dataset = f"{start}_{end}_{len(arts)}_{digest}"       # đổi bộ bài → đổi mã → CSV cũ không bị trộn nhầm
    summaries: dict[str, dict] = {}
    for f in sorted((Path(out_dir) / "llm").glob("tom_tat_*.json")):
        summaries.update(json.loads(f.read_text(encoding="utf-8")))
    shown = [{**a, "summary": summaries[str(stt)]} if str(stt) in summaries else a for stt, a in enumerate(arts, 1)]
    data = {"dataset": dataset, "start": start, "end": end,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "articles": shown, "suggest": suggest(arts, k=k, terms=5)}
    # "<" → <: văn bản bài (vd. "</script>", "<!--") không thể làm vỡ thẻ <script> chứa dữ liệu
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cong_cu_gan.html").write_text(html, encoding="utf-8")
    with open(out / "articles.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps({"stt": stt, **a}, ensure_ascii=False) + "\n" for stt, a in enumerate(arts, 1))
    meta = {"dataset": dataset, "start": start, "end": end, "n": len(arts)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out / "cong_cu_gan.html"


def _articles(out_dir: str | Path) -> list[dict]:
    path = Path(out_dir) / "articles.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"chưa có {path} — chạy `make gold-tool` (ở gốc repo) để sinh công cụ gán trước")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _read_labels(path: str | Path) -> list[dict]:
    if not Path(path).exists():
        raise FileNotFoundError(f"không thấy file nhãn {Path(path).resolve()} — file này có được sau khi gán xong và bấm "
                                "Xuất CSV trong công cụ (thường nằm ở thư mục Downloads)")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def clusters_from_links(order: list[str], links: dict[str, str]) -> dict[str, str]:
    """Liên kết → mã cụm (C0001… theo thứ tự xuất hiện trong `order`). Bài chưa gán hoặc bị loại (x) không có mã.

    Liên kết có thể trỏ tới bài ngoài `order` (bài người khác gán): vẫn dùng để nối, chỉ không trả mã cho bài đó.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, link in links.items():
        find(a)
        if link not in ("", EXCLUDED):
            parent[find(a)] = find(link)
    names: dict[str, str] = {}
    out = {}
    for a in order:
        if a in links and links[a] != EXCLUDED:
            root = find(a)
            names.setdefault(root, f"C{len(names) + 1:04d}")
            out[a] = names[root]
    return out


def _links(rows: list[dict]) -> dict[str, str]:
    return {r["article_id"]: (r.get("link_to") or "").strip() for r in rows}


def merge(out_dir: str | Path, label_csvs: list[str | Path], out_name: str = "gold_clusters.csv") -> Path:
    """Gộp CSV của nhiều người (mỗi người một đoạn) thành tập vàng. Một bài bị gán ở hai file → báo lỗi."""
    arts = _articles(out_dir)
    links: dict[str, str] = {}
    owner: dict[str, tuple[str, dict]] = {}
    dup = []
    for path in label_csvs:
        for r in _read_labels(path):
            aid = r["article_id"]
            if aid in owner:
                dup.append(f"{aid} ({owner[aid][0]} và {path})")
            owner[aid] = (str(path), r)
            links[aid] = (r.get("link_to") or "").strip()
    if dup:
        raise ValueError("bài bị gán hai lần — chọn một bản rồi gộp lại: " + "; ".join(dup[:10]))
    order = [a["id"] for a in arts]
    cl = clusters_from_links(order, links)
    out = Path(out_dir) / out_name
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cluster_id", "article_id", "stt", "published_at", "source", "title", "annotator", "unsure"])
        for a in sorted((a for a in arts if a["id"] in cl), key=lambda a: (cl[a["id"]], a["stt"])):
            r = owner[a["id"]][1]
            w.writerow([cl[a["id"]], a["id"], a["stt"], a["t"], a["source"], a["title"], r.get("annotator", ""),
                        r.get("unsure", "")])
    sizes = np.bincount([int(c[1:]) for c in cl.values()])[1:]
    n_x = sum(v == EXCLUDED for v in links.values())
    print(f"{len(cl)} bài trong {len(sizes)} cụm ({int((sizes >= 2).sum())} cụm ≥ 2 bài, lớn nhất {sizes.max()}) · "
          f"loại {n_x} · chưa gán {len(arts) - len(cl) - n_x}/{len(arts)} → {out}")
    return out


def agree(out_dir: str | Path, csv_a: str | Path, csv_b: str | Path) -> dict:
    """B-Cubed giữa hai người gán CÙNG một đoạn (độc lập) + danh sách bài mà hai người xếp khác bạn cùng cụm."""
    arts = _articles(out_dir)
    order = [a["id"] for a in arts]
    title = {a["id"]: a for a in arts}
    la, lb = _links(_read_labels(csv_a)), _links(_read_labels(csv_b))
    both = [i for i in order if i in la and i in lb]
    x_mismatch = [i for i in both if (la[i] == EXCLUDED) != (lb[i] == EXCLUDED)]
    common = [i for i in both if la[i] != EXCLUDED and lb[i] != EXCLUDED]
    keep = set(common)
    ca = {i: c for i, c in clusters_from_links(order, la).items() if i in keep}
    cb = {i: c for i, c in clusters_from_links(order, lb).items() if i in keep}
    p, r, f1 = bcubed(cb, ca)
    mates_a, mates_b = {}, {}
    for cl, mates in ((ca, mates_a), (cb, mates_b)):
        groups: dict[str, set[str]] = {}
        for i, c in cl.items():
            groups.setdefault(c, set()).add(i)
        for i, c in cl.items():
            mates[i] = groups[c] - {i}
    fmt = lambda ids: " | ".join(title[j]["title"][:70] for j in sorted(ids, key=lambda j: title[j]["stt"]))
    row = lambda i, only_a, only_b: {"stt": title[i]["stt"], "article_id": i, "title": title[i]["title"],
                                     "chi_A_gop": only_a, "chi_B_gop": only_b}
    disagreements = [row(i, fmt(mates_a[i] - mates_b[i]), fmt(mates_b[i] - mates_a[i]))
                     for i in common if mates_a[i] != mates_b[i]]
    disagreements += [row(i, "x (loại)" if la[i] == EXCLUDED else "", "x (loại)" if lb[i] == EXCLUDED else "")
                      for i in x_mismatch]
    return {"n": len(common), "precision": p, "recall": r, "f1": f1, "n_x_mismatch": len(x_mismatch),
            "disagreements": sorted(disagreements, key=lambda d: d["stt"])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="sinh công cụ gán (HTML tự chứa)")
    b.add_argument("--silver-glob", default=DEFAULT_SILVER)
    b.add_argument("--start", required=True, help="ngày đầu, vd. 2026-09-14")
    b.add_argument("--end", required=True, help="ngày SAU ngày cuối (không lấy), vd. 2026-09-16")
    b.add_argument("--k", type=int, default=12, help="số bài gợi ý TF-IDF mỗi bài")
    m = sub.add_parser("merge", help="gộp CSV của nhiều người thành tập vàng")
    m.add_argument("csv", nargs="+")
    g = sub.add_parser("agree", help="đồng thuận B-Cubed giữa hai người gán cùng một đoạn")
    g.add_argument("csv_a")
    g.add_argument("csv_b")
    for p in (b, m, g):
        p.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    try:
        _run(args)
    except FileNotFoundError as e:
        raise SystemExit(f"Lỗi: {e}") from None


def _run(args: argparse.Namespace) -> None:
    if args.cmd == "build":
        html = build(args.silver_glob, args.start, args.end, args.out, k=args.k)
        meta = json.loads((Path(args.out) / "meta.json").read_text(encoding="utf-8"))
        print(f"{meta['n']} bài · mã bộ dữ liệu {meta['dataset']} → {html} ({html.stat().st_size / 1e6:.1f} MB)")
    elif args.cmd == "merge":
        merge(args.out, args.csv)
    else:
        res = agree(args.out, args.csv_a, args.csv_b)
        out = Path(args.out) / "dong_thuan_lech.csv"
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["stt", "article_id", "title", "chi_A_gop", "chi_B_gop"])
            w.writeheader()
            w.writerows(res["disagreements"])
        verdict = "ĐẠT cổng ≥ 0,7" if res["f1"] >= 0.7 else "CHƯA ĐẠT 0,7 → xem bài lệch, sửa hướng dẫn, gán thử lại"
        print(f"{res['n']} bài chung · B-Cubed P={res['precision']:.3f} R={res['recall']:.3f} F1={res['f1']:.3f} "
              f"({verdict}) · lệch x/không-x: {res['n_x_mismatch']} · {len(res['disagreements'])} bài lệch → {out}")


if __name__ == "__main__":
    main()
