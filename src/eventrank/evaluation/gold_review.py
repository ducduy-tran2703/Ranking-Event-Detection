"""Tập vàng gom cụm, cách 2: Claude ĐỀ XUẤT cụm, người DUYỆT trên màn hình trực quan.

    # 1) Gom thô thành nhóm (TF-IDF + MiniLM, ngưỡng lỏng) và chia việc cho agent
    uv run python -m eventrank.evaluation.gold_review blocks
        → data/gold_clusters/v1/llm/{blocks.json, input_01.md …}
    # 2) Mỗi agent Claude đọc input_XX.md, ghi output_XX.json (xem LLM_INSTRUCTIONS)
    # 3) Kiểm tra kết quả agent + sinh màn hình duyệt
    uv run python -m eventrank.evaluation.gold_review review
        → data/gold_clusters/v1/{proposals.json, duyet_cum.html, llm/claude_de_xuat.csv}
    # 4) Người duyệt mở duyet_cum.html, sửa, Xuất CSV → dùng `gold_clusters merge/agree` như cách 1

Vì sao gom thô: người không nhớ được 1.500 bài; Claude không đọc tốt 1.500 bài một lúc. Nhóm = thành phần liên thông
của cạnh "trong 48h VÀ (TF-IDF ≥ 0,15 HOẶC MiniLM ≥ 0,60)"; nhóm > 120 bài được chia lại với ngưỡng chặt hơn. Đo trên
80 cặp v4 mức 3 nằm trong cửa sổ 14–15/09: 78 cặp (97,5%) nằm chung nhóm, 0/24 cặp mức 0 chung nhóm. Giới hạn 40 bài/nhóm
chỉ giữ được 80% vì cắt vụn sự kiện lớn (chuyến thăm của Nhà vua Thái Lan ~45 bài) → dùng 120.
MiniLM khác họ với bkai/e5 (hai mô hình được chấm), như ở weak_labels/dense.py.

HẠN CHẾ phải ghi trong báo cáo: dữ liệu train v4 do Claude gán → đáp án do Claude đề xuất có lợi cho mô hình fine-tune.
Đối chứng: một đoạn 100 bài người gán MÙ (công cụ gold_clusters, làm TRƯỚC khi xem đề xuất), so với đề xuất và bản duyệt.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from eventrank.evaluation.gold_clusters import DEFAULT_OUT, ROOT, _articles

DENSE_NPZ = ROOT / "data/weak_labels/cache/Xenova__paraphrase-multilingual-MiniLM-L12-v2.npz"
TEMPLATE = Path(__file__).with_name("gold_review.html")

LLM_INSTRUCTIONS = """\
Bạn chia các bài báo tiếng Việt thành SỰ KIỆN. Mỗi nhóm dưới đây gồm các bài có thể liên quan (gom thô, lỏng).
Với MỖI nhóm có ≥ 2 bài: chia các bài của nhóm thành các cụm, mỗi cụm = các bài về CÙNG MỘT sự kiện tin tức.

Cùng sự kiện (cùng cụm) — hai bài kể về CÙNG MỘT VIỆC CỤ THỂ:
- khác báo, khác cách viết, khác khía cạnh của chính việc đó (con số, nhân chứng, phát biểu tại cùng buổi);
- tin trước và tin sau cùng việc: "sắp thăm" ↔ "đã thăm"; nhận định / lịch phát sóng trước trận ↔ kết quả ↔ phản ứng,
  trọng tài/VAR, phân tích CHÍNH trận đó; họp bắt đầu ↔ kết quả cùng cuộc họp;
- phản ứng/hệ quả trực tiếp trong vài ngày ("vụ cháy" ↔ "lãnh đạo thăm nạn nhân vụ cháy"; "X bị bắt" ↔ "X bị khởi tố");
- các hoạt động trong CÙNG MỘT chuyến thăm / hội nghị / đợt tập trung của CÙNG đoàn, cùng nhân vật (lễ đón ↔ hội đàm ↔
  tiệc chiêu đãi ↔ tuyên bố chung).
Khác sự kiện (khác cụm), dù cùng chủ đề:
- hai trận khác nhau của cùng một đội; hai diễn biến khác nhau của cùng một xung đột; các giai đoạn vụ án cách nhau lâu;
- cùng hội nghị / buổi lễ nhưng chủ thể khác (hai đoàn, hai doanh nghiệp); hai chặng ở hai nước;
- chuỗi định kỳ khác ngày ("Giá vàng 14/9" ↔ "Giá vàng 15/9"); cùng khuôn tin khác đối tượng (điểm chuẩn hai trường);
- bình luận/phân tích chung (không gắn với một việc cụ thể) ↔ tin cụ thể; chỉ chung đội bóng / nhân vật / lĩnh vực.
Ví dụ: "MU thua Man City" ↔ "Trọng tài nhận sai bàn thắng trận MU–Man City" ↔ "Trọng tài VAR bị đình chỉ" = CÙNG cụm;
"MU muốn mua Xavi Espart" và "Scholes: Man Utd khó vô địch với Lammens" = mỗi bài một cụm riêng.

Loại (x): bài TỔNG HỢP nhiều tin ("Tin tức thế giới 14/9: …", "Thời sự 24h", "Kết quả bóng đá hôm nay …", "Tin sáng"),
hoặc không hiểu được bài nói gì. Áp dụng cả cho các bài lẻ ở cuối file: chỉ liệt kê bài lẻ nào cần loại.

Mỗi cụm đặt TÊN 5–12 từ nêu VIỆC: ai – làm gì – khi nào ("MU thua Man City 2-1 ngày 13/9"). Độ tin "cao" hoặc "thấp"
(thấp = phân vân ranh giới cùng/khác sự kiện → người duyệt sẽ xem kỹ). Chỉ dùng tiêu đề, sapo, báo, giờ đăng; không tra cứu.
Mọi bài của một nhóm phải nằm trong ĐÚNG MỘT cụm hoặc trong x. Dùng số trong ngoặc vuông [STT] để chỉ bài.

Ghi kết quả ra file JSON (UTF-8), đúng dạng:
{"<số nhóm>": {"clusters": [{"name": "…", "members": [STT, …], "confidence": "cao"}, …], "x": [STT, …]}, …,
 "le": {"x": [STT của bài lẻ cần loại]}}
"""


def similarities(arts: list[dict], dense_npz: str | Path = DENSE_NPZ) -> tuple[np.ndarray, np.ndarray]:
    """Ma trận cosine TF-IDF (tiêu đề + sapo, giống công cụ gán) và MiniLM (vector có sẵn của nhãn yếu)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    X = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, token_pattern=r"(?u)\b\w+\b").fit_transform(
        [f"{a['title']}. {a['sapo']}" for a in arts])
    z = np.load(dense_npz, allow_pickle=True)
    emb = dict(zip(z["ids"], z["emb"], strict=True))
    missing = [a["id"] for a in arts if a["id"] not in emb]
    if missing:
        raise ValueError(f"{len(missing)} bài chưa có vector MiniLM trong {dense_npz} — chạy `make embed`")
    E = np.stack([emb[a["id"]] for a in arts]).astype(np.float32)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    return (X @ X.T).toarray(), E @ E.T


def make_blocks(arts: list[dict], T: np.ndarray, M: np.ndarray, tfidf_th: float = 0.15, dense_th: float = 0.60,
                cap: int = 120, window_hours: float = 48, step: tuple[float, float] = (0.05, 0.03)) -> list[list[int]]:
    """Nhóm = thành phần liên thông; nhóm > cap bài được chia lại với ngưỡng chặt hơn (lặp tới khi ≤ cap)."""
    t = np.array([datetime.fromisoformat(a["t"]).timestamp() for a in arts])
    near = np.abs(t[:, None] - t[None, :]) <= window_hours * 3600

    def split(members: list[int], a1: float, a2: float) -> list[list[int]]:
        ms = np.array(members)
        edge = near[np.ix_(ms, ms)] & ((T[np.ix_(ms, ms)] >= a1) | (M[np.ix_(ms, ms)] >= a2))
        parent = list(range(len(ms)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for u, v in zip(*np.nonzero(np.triu(edge, 1)), strict=True):
            parent[find(u)] = find(v)
        groups: dict[int, list[int]] = {}
        for k, i in enumerate(ms):
            groups.setdefault(find(k), []).append(int(i))
        out = []
        for g in groups.values():
            stuck = a1 > 1 and a2 > 1                      # văn bản trùng hệt: không chia được nữa
            out += split(g, a1 + step[0], a2 + step[1]) if len(g) > cap and not stuck else [g]
        return out

    return sorted((sorted(b) for b in split(list(range(len(arts))), tfidf_th, dense_th)), key=lambda b: b[0])


def split_parts(blocks: list[list[int]], n_parts: int) -> list[list[int]]:
    """Chia nhóm cho n agent, cân theo số bài (nhóm lớn trước); không cắt nhóm. Trả về chỉ số nhóm của mỗi phần."""
    load = [0.0] * n_parts
    parts: list[list[int]] = [[] for _ in range(n_parts)]
    for b in sorted(range(len(blocks)), key=lambda b: -len(blocks[b])):
        k = min(range(n_parts), key=lambda k: load[k])
        parts[k].append(b)
        load[k] += len(blocks[b]) if len(blocks[b]) > 1 else 0.3     # bài lẻ chỉ cần xem có phải bài tổng hợp
    return [sorted(p) for p in parts if p]


def write_parts(out_dir: str | Path, arts: list[dict], blocks: list[list[int]], parts: list[list[int]]) -> list[Path]:
    llm = Path(out_dir) / "llm"
    llm.mkdir(parents=True, exist_ok=True)
    (llm / "blocks.json").write_text(json.dumps(blocks), encoding="utf-8")
    line = lambda i: (f"[{arts[i]['stt']}] {arts[i]['t'][8:10]}/{arts[i]['t'][5:7]} {arts[i]['t'][11:16]} "
                      f"{arts[i]['source']} | {arts[i]['title']} | {arts[i]['sapo']}")
    paths = []
    for k, part in enumerate(parts, 1):
        multi = [b for b in part if len(blocks[b]) > 1]
        single = [b for b in part if len(blocks[b]) == 1]
        text = [LLM_INSTRUCTIONS, f"\n# Phần {k:02d}: {len(multi)} nhóm, {len(single)} bài lẻ\n"]
        for b in multi:
            text.append(f"\n## Nhóm {b} ({len(blocks[b])} bài)")
            text += [line(i) for i in blocks[b]]
        text.append("\n## Bài lẻ (chỉ cần liệt kê bài nào phải loại vào \"le\": {\"x\": [...]})")
        text += [line(blocks[b][0]) for b in single]
        p = llm / f"input_{k:02d}.md"
        p.write_text("\n".join(text) + "\n", encoding="utf-8")
        paths.append(p)
    return paths


def check_proposals(arts: list[dict], blocks: list[list[int]], outputs: dict) -> tuple[list[dict], list[str]]:
    """Đổi STT (1-based) của agent → chỉ số; kiểm tra mỗi bài đúng một lần. Thiếu → cụm lẻ 'thấp'; sai → ValueError."""
    idx = {a["stt"]: i for i, a in enumerate(arts)}
    le_x = {idx[s] for s in (outputs.get("le") or {}).get("x", []) if s in idx}
    proposals, problems = [], []
    for b, members in enumerate(blocks):
        out = outputs.get(str(b))
        mem = set(members)
        seen: set[int] = set()

        def take(stts: list, where: str, b: int = b, mem: set = mem, seen: set = seen) -> list[int]:
            got = []
            for s in stts:
                i = idx.get(int(s))
                if i is None or i not in mem:
                    raise ValueError(f"nhóm {b}: bài STT {s} ở {where} nằm ngoài nhóm")
                if i in seen:
                    raise ValueError(f"nhóm {b}: bài STT {s} xuất hiện hai lần")
                seen.add(i)
                got.append(i)
            return sorted(got)

        if out is None:
            if len(members) > 1:
                problems.append(f"nhóm {b}: agent không trả kết quả → mỗi bài một cụm, tin thấp")
            conf = "cao" if len(members) == 1 else "thấp"
            clusters = [{"name": "", "members": [i], "confidence": conf} for i in members if i not in le_x]
            proposals.append({"members": members, "clusters": clusters, "x": sorted(mem & le_x)})
            continue
        clusters = [{"name": str(c.get("name", "")).strip(), "members": take(c.get("members", []), "cụm"),
                     "confidence": "thấp" if c.get("confidence") == "thấp" else "cao"}
                    for c in out.get("clusters", [])]
        x = take(out.get("x", []), "x")
        clusters = [c for c in clusters if c["members"]]
        lost = sorted(mem - seen)
        if lost:
            problems.append(f"nhóm {b}: agent thiếu {len(lost)} bài (STT {[arts[i]['stt'] for i in lost]}) → cụm lẻ, tin thấp")
            clusters += [{"name": "(Claude bỏ sót)", "members": [i], "confidence": "thấp"} for i in lost]
        clusters.sort(key=lambda c: c["members"][0])
        proposals.append({"members": members, "clusters": clusters, "x": x})
    return proposals, problems


def proposal_rows(arts: list[dict], proposals: list[dict], dataset: str) -> list[dict]:
    """Đề xuất của Claude dưới dạng CSV của công cụ gán (link_to = bài sớm nhất của cụm) → so được bằng `agree`."""
    link = {}
    for p in proposals:
        for c in p["clusters"]:
            first = min(c["members"])
            link.update({i: "" if i == first else arts[first]["id"] for i in c["members"]})
        link.update({i: "x" for i in p["x"]})
    return [{"dataset": dataset, "annotator": "claude", "stt": a["stt"], "article_id": a["id"], "link_to": link[i],
             "unsure": 0, "labeled_at": ""} for i, a in enumerate(arts) if i in link]


def build_review(arts: list[dict], proposals: list[dict], dataset: str, out_dir: str | Path) -> Path:
    keep = ("stt", "id", "t", "source", "title", "sapo", "body", "url")
    data = {"dataset": dataset, "articles": [{k: a.get(k, "") for k in keep} for a in arts], "blocks": proposals}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    out = Path(out_dir) / "duyet_cum.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("blocks", help="gom thô + chia việc cho agent")
    b.add_argument("--parts", type=int, default=8)
    sub.add_parser("review", help="kiểm tra kết quả agent + sinh màn hình duyệt")
    for p in sub.choices.values():
        p.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out = Path(args.out)
    arts = _articles(out)

    if args.cmd == "blocks":
        blocks = make_blocks(arts, *similarities(arts))
        sizes = np.array([len(x) for x in blocks])
        paths = write_parts(out, arts, blocks, split_parts(blocks, args.parts))
        print(f"{len(blocks)} nhóm: {int((sizes > 1).sum())} nhóm ≥ 2 bài ({int(sizes[sizes > 1].sum())} bài), "
              f"{int((sizes == 1).sum())} bài lẻ, lớn nhất {sizes.max()} → {len(paths)} phần ở {paths[0].parent}")
        return
    blocks = json.loads((out / "llm" / "blocks.json").read_text(encoding="utf-8"))
    outputs: dict = {"le": {"x": []}}
    files = sorted((out / "llm").glob("output_*.json"))
    for f in files:
        o = json.loads(f.read_text(encoding="utf-8"))
        outputs["le"]["x"] += (o.pop("le", None) or {}).get("x", [])
        outputs.update(o)
    proposals, problems = check_proposals(arts, blocks, outputs)
    (out / "proposals.json").write_text(json.dumps(proposals, ensure_ascii=False), encoding="utf-8")
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    html = build_review(arts, proposals, meta["dataset"], out)
    rows = proposal_rows(arts, proposals, meta["dataset"])
    with open(out / "llm" / "claude_de_xuat.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    n_cl = sum(len(p["clusters"]) for p in proposals)
    n_low = sum(c["confidence"] == "thấp" for p in proposals for c in p["clusters"])
    n_x = sum(len(p["x"]) for p in proposals)
    print(f"{len(files)} file kết quả · {n_cl} cụm đề xuất ({n_low} tin thấp) · loại {n_x} bài → {html}")
    for p in problems:
        print("  ⚠", p)


if __name__ == "__main__":
    main()
