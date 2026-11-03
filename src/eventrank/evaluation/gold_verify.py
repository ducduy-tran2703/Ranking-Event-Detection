"""Vòng kiểm tra tập vàng do Claude đề xuất: B (kiểm từng cụm) + C (tìm cụm bị tách) + áp quy tắc ranh giới R1–R6.

    uv run --group embed --with pyvi python -m eventrank.evaluation.gold_verify prep --parts-b 6 --parts-c 2
        → data/gold_clusters/v1/llm/verify/{clusters.json, candidates.json, b_XX.md, c_XX.md}
    # agent đọc b_XX.md → ghi b_XX.json ; đọc c_XX.md → ghi c_XX.json
    uv run python -m eventrank.evaluation.gold_verify apply
        → proposals_v2.json + llm/verify/thay_doi.md (mọi chỗ sửa, kèm lý do) + duyet_cum.html + llm/claude_de_xuat_v2.csv

B — mỗi cụm ≥ 2 bài (và mọi cụm Claude ghi "không chắc"): agent đọc tóm tắt toàn văn từng bài, giữ nguyên / tách / loại.
    Bắt lỗi GỘP NHẦM.
C — cặp cụm (kể cả cụm 1 bài) khác nhau nhưng có bài rất gần nghĩa trong 48h (embedding bkai fine-tune, cosine ≥ 0,85 —
    ở ngưỡng này nối cặp đã cho recall 0,97 với đề xuất cũ): agent quyết gộp hay không. Bắt lỗi TÁCH NHẦM do gom thô.
Embedding chỉ đề xuất cặp để xem; quyết định là của agent theo định nghĩa + quy tắc ranh giới.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from eventrank.evaluation.gold_clusters import DEFAULT_OUT, ROOT, _articles

RULES_DOC = ROOT / "docs/huong-dan-gan-4-muc.md"


def cluster_list(proposals: list[dict]) -> list[dict]:
    """Mọi cụm của đề xuất, sắp theo bài sớm nhất, mã ổn định K0001…"""
    cl = [{"name": c["name"], "members": sorted(c["members"]), "confidence": c["confidence"]}
          for p in proposals for c in p["clusters"] if c["members"]]
    cl.sort(key=lambda c: c["members"][0])
    for k, c in enumerate(cl, 1):
        c["id"] = f"K{k:04d}"
    return cl


def merge_candidates(clusters: list[dict], E: np.ndarray, times: np.ndarray, threshold: float = 0.85,
                     window_hours: float = 48) -> list[dict]:
    """Cặp cụm khác nhau có ít nhất một cặp bài trong 48h với cosine ≥ threshold; giữ cặp bài gần nhất làm ví dụ."""
    owner = {i: c["id"] for c in clusters for i in c["members"]}
    S = E @ E.T
    near = np.abs(times[:, None] - times[None, :]) <= window_hours * 3600
    best: dict[tuple[str, str], tuple[float, int, int]] = {}
    for i, j in zip(*np.nonzero(np.triu((S >= threshold) & near, 1)), strict=True):
        a, b = owner.get(int(i)), owner.get(int(j))
        if a is None or b is None or a == b:
            continue
        key = (a, b) if a < b else (b, a)
        if key not in best or S[i, j] > best[key][0]:
            best[key] = (float(S[i, j]), int(i), int(j))
    return [{"a": a, "b": b, "score": round(s, 3), "via": [i, j]}
            for (a, b), (s, i, j) in sorted(best.items(), key=lambda kv: -kv[1][0])]


def apply(arts: list[dict], clusters: list[dict], verdicts: dict, merges: dict,
          candidates: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    """Áp kết quả B (tách/loại trong một cụm, STT 1-based) rồi C (gộp cặp cụm). Trả về (cụm mới, nhật ký thay đổi).

    Bài bị loại (x) ở B không còn trong cụm nào; gọi `excluded_by(verdicts)` để lấy danh sách.
    """
    idx = {a["stt"]: i for i, a in enumerate(arts)}
    title = lambda i: arts[i]["title"][:70]
    log: list[str] = []
    out: list[dict] = []
    home: dict[int, int] = {}                        # bài → chỉ số cụm trong out
    for c in clusters:
        v = verdicts.get(c["id"])
        if v is None:
            groups = [{"name": c["name"], "members": c["members"], "confidence": c["confidence"]}]
        else:
            groups = [{"name": g.get("name") or c["name"], "members": sorted(idx[int(s)] for s in g.get("members", [])),
                       "confidence": g.get("confidence", "cao")} for g in v.get("groups", [])]
            xs = sorted(idx[int(s)] for s in v.get("x", []))
            got = sorted([i for g in groups for i in g["members"]] + xs)
            if got != c["members"]:
                raise ValueError(f"{c['id']}: kết quả kiểm không chia đúng các bài của cụm "
                                 f"(thiếu {sorted(set(c['members']) - set(got))}, thừa {sorted(set(got) - set(c['members']))})")
            groups = [g for g in groups if g["members"]]
            reason = v.get("ly_do", "")
            if len(groups) > 1:
                log.append(f"- **tách** {c['id']} «{c['name']}» thành {len(groups)} cụm: "
                           + " / ".join(f"«{g['name']}» ({len(g['members'])} bài)" for g in groups) + (f" — {reason}" if reason else ""))
            for i in xs:
                log.append(f"- **loại** [{arts[i]['stt']}] {title(i)} khỏi {c['id']} — {reason}")
        for g in groups:
            g["src"] = c["id"]
            for i in g["members"]:
                home[i] = len(out)
            out.append(g)
    via = {f"{p['a']}|{p['b']}": p["via"] for p in candidates or []}
    first = {c["id"]: c["members"][0] for c in clusters}
    parent = list(range(len(out)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for key, m in merges.items():
        if not m.get("gop"):
            continue
        a, b = key.split("|")
        i, j = via.get(key, [first[a], first[b]])
        if i not in home or j not in home:
            continue                                  # một bên đã bị loại ở B
        ra, rb = find(home[i]), find(home[j])
        if ra != rb:
            parent[rb] = ra
            log.append(f"- **gộp** {a} «{out[home[i]]['name']}» + {b} «{out[home[j]]['name']}»"
                       + (f" — {m.get('ly_do')}" if m.get("ly_do") else ""))
    merged: dict[int, dict] = {}
    for k, g in enumerate(out):
        r = find(k)
        if r not in merged:
            merged[r] = {"name": out[r]["name"], "members": [], "confidence": out[r]["confidence"], "src": []}
        merged[r]["members"] += g["members"]
        merged[r]["src"].append(g["src"])
    final = [dict(c, members=sorted(c["members"])) for c in merged.values()]
    final.sort(key=lambda c: c["members"][0])
    return final, log


def excluded_by(arts: list[dict], verdicts: dict) -> list[int]:
    idx = {a["stt"]: i for i, a in enumerate(arts)}
    return sorted(idx[int(s)] for v in verdicts.values() for s in v.get("x", []))


# ---------------------------------------------------------------- chuẩn bị đầu vào cho agent
def _rules() -> str:
    doc = RULES_DOC.read_text(encoding="utf-8")
    return doc[doc.index("## Bốn mức"):doc.index("## Gán tay (cho người)")]


def _line(a: dict, s: dict | None) -> str:
    s = s or {}
    return (f"[{a['stt']}] {a['t'][8:10]}/{a['t'][5:7]} {a['t'][11:16]} · {a['source']} | {a['title']}\n"
            f"    Sự việc: {s.get('su_viec', '(chưa có)')} · Dạng: {s.get('dang_bai', '?')}\n"
            f"    Tóm tắt: {s.get('tom_tat', a.get('sapo', ''))}")


HEAD_B = """Bạn KIỂM TRA các cụm sự kiện do một người gán khác đề xuất. Mỗi cụm "## Kxxxx" gồm các bài (STT, giờ, báo, tiêu đề,
sự việc + tóm tắt viết từ TOÀN VĂN bài). Với MỖI cụm, đọc hết các bài và quyết định theo định nghĩa + QUY TẮC RANH GIỚI R1–R6
dưới đây (đã được nhóm duyệt — ưu tiên áp dụng đúng các quy tắc này):
- mọi bài cùng một sự kiện → giữ nguyên (một nhóm duy nhất);
- có bài khác sự kiện → TÁCH thành các nhóm, mỗi nhóm một sự kiện (bài lạc đứng riêng thành nhóm 1 bài);
- bài tổng hợp nhiều tin / bảng xếp hạng nhiều trận (R4) → đưa vào "x".
Đặt lại tên nhóm nếu cần (5–12 từ: ai – làm gì – khi nào). Độ tin "cao" hoặc "thấp".

{rules}

Ghi JSON UTF-8, MỖI cụm trong file một khoá (kể cả khi giữ nguyên):
{{"K0001": {{"groups": [{{"name": "…", "members": [STT, …], "confidence": "cao"}}], "x": [], "ly_do": "≤ 20 từ, chỉ khi tách/loại"}}, …}}
groups + x phải chứa ĐÚNG các STT của cụm đó, mỗi STT một lần.
"""

HEAD_C = """Mỗi mục "## Kxxxx|Kyyyy" là HAI cụm sự kiện đang tách riêng nhưng có bài rất gần nghĩa. Đọc các bài của cả hai cụm
(sự việc + tóm tắt viết từ TOÀN VĂN) và quyết định: hai cụm có phải CÙNG MỘT sự kiện không — theo định nghĩa + QUY TẮC
RANH GIỚI R1–R6 dưới đây (đã được nhóm duyệt). Chỉ cùng chủ đề / cùng câu chuyện / cùng loại tin thì KHÔNG gộp.

{rules}

Ghi JSON UTF-8, MỖI mục một khoá: {{"Kxxxx|Kyyyy": {{"gop": true, "ly_do": "≤ 20 từ"}}, …}}
"""


def prep(out_dir: Path, parts_b: int, parts_c: int, threshold: float) -> None:
    from eventrank.evaluation.gold_viz import _embed

    arts = _articles(out_dir)
    proposals = json.loads((out_dir / "proposals.json").read_text(encoding="utf-8"))
    summ: dict[str, dict] = {}
    for f in sorted((out_dir / "llm").glob("tom_tat_[0-9]*.json")):
        summ.update(json.loads(f.read_text(encoding="utf-8")))
    missing = [a["stt"] for a in arts if str(a["stt"]) not in summ]
    if missing:
        print(f"⚠ {len(missing)} bài chưa có tóm tắt (vd. {missing[:5]}) — agent sẽ chỉ thấy sapo của các bài này")
    clusters = cluster_list(proposals)
    E = _embed(arts, out_dir / "emb_bkai_ft.npz")
    times = np.array([datetime.fromisoformat(a["t"]).timestamp() for a in arts])
    cands = merge_candidates(clusters, E, times, threshold)
    vdir = out_dir / "llm" / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")
    (vdir / "candidates.json").write_text(json.dumps(cands, ensure_ascii=False), encoding="utf-8")
    rules = _rules()
    by_id = {c["id"]: c for c in clusters}
    block = lambda c: (f"\n## {c['id']} · «{c['name']}» · {len(c['members'])} bài · độ tin {c['confidence']}\n"
                       + "\n".join(_line(arts[i], summ.get(str(arts[i]["stt"]))) for i in c["members"]))
    todo_b = [c for c in clusters if len(c["members"]) >= 2 or c["confidence"] == "thấp"]
    todo_b.sort(key=lambda c: -len(c["members"]))
    load = [0] * parts_b
    bins: list[list[dict]] = [[] for _ in range(parts_b)]
    for c in todo_b:                                 # cân theo số bài, cụm lớn trước
        k = load.index(min(load))
        bins[k].append(c)
        load[k] += len(c["members"])
    for k, part in enumerate(bins, 1):
        (vdir / f"b_{k:02d}.md").write_text(HEAD_B.format(rules=rules) + "".join(block(c) for c in part) + "\n",
                                            encoding="utf-8")
    def short(c: dict, via: int, cap: int = 6) -> str:
        # cụm lớn lặp lại ở nhiều cặp → chỉ in bài gần cụm kia nhất + các bài mới nhất (tối đa cap bài)
        shown = [via] + [i for i in reversed(c["members"]) if i != via][: cap - 1]
        more = len(c["members"]) - len(shown)
        return (f"\n### {c['id']} · «{c['name']}» · {len(c['members'])} bài" + (f" (in {len(shown)} bài)" if more else "")
                + "\n" + "\n".join(_line(arts[i], summ.get(str(arts[i]["stt"]))) for i in sorted(shown)))

    for k in range(parts_c):
        part = cands[k::parts_c]
        text = HEAD_C.format(rules=rules) + "".join(
            f"\n## {p['a']}|{p['b']} (cosine {p['score']})" + short(by_id[p["a"]], p["via"][0] if p["via"][0] in by_id[p["a"]]["members"] else p["via"][1])
            + short(by_id[p["b"]], p["via"][1] if p["via"][1] in by_id[p["b"]]["members"] else p["via"][0]) for p in part)
        (vdir / f"c_{k + 1:02d}.md").write_text(text + "\n", encoding="utf-8")
    print(f"{len(clusters)} cụm · vòng B: {len(todo_b)} cụm ({sum(load)} bài) → {parts_b} phần · "
          f"vòng C: {len(cands)} cặp ứng viên (cosine ≥ {threshold}) → {parts_c} phần · {vdir}")


def apply_cli(out_dir: Path) -> None:
    from eventrank.evaluation.gold_review import build_review, proposal_rows

    arts = _articles(out_dir)
    vdir = out_dir / "llm" / "verify"
    clusters = json.loads((vdir / "clusters.json").read_text(encoding="utf-8"))
    cands = json.loads((vdir / "candidates.json").read_text(encoding="utf-8"))
    verdicts: dict = {}
    for f in sorted(vdir.glob("b_*.json")):
        verdicts.update(json.loads(f.read_text(encoding="utf-8")))
    merges: dict = {}
    for f in sorted(vdir.glob("c_*.json")):
        merges.update(json.loads(f.read_text(encoding="utf-8")))
    old = json.loads((out_dir / "proposals.json").read_text(encoding="utf-8"))
    final, log = apply(arts, clusters, verdicts, merges, cands)
    x = sorted(set(excluded_by(arts, verdicts)) | {i for p in old for i in p["x"]})
    final = [dict(c, members=[i for i in c["members"] if i not in set(x)]) for c in final]
    final = [c for c in final if c["members"]]
    v2 = [{"members": sorted(i for c in final for i in c["members"]) + x, "clusters": final, "x": x}]
    (out_dir / "proposals_v2.json").write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
    multi = sum(len(c["members"]) >= 2 for c in final)
    head = (f"# Thay đổi sau vòng kiểm tra B + C (quy tắc R1–R6)\n\nTrước: {len(clusters)} cụm. Sau: {len(final)} cụm "
            f"({multi} cụm ≥ 2 bài), loại {len(x)} bài. Đã kiểm {len(verdicts)} cụm, xét {len(merges)} cặp gộp "
            f"({sum(bool(m.get('gop')) for m in merges.values())} cặp gộp).\n\n")
    (vdir / "thay_doi.md").write_text(head + "\n".join(log) + "\n", encoding="utf-8")
    dataset = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))["dataset"]
    build_review(arts, v2, dataset, out_dir)
    rows = proposal_rows(arts, v2, dataset)
    with open(out_dir / "llm" / "claude_de_xuat_v2.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(head.strip().splitlines()[-1] + f"\n{len(log)} thay đổi → {vdir / 'thay_doi.md'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--parts-b", type=int, default=6)
    p.add_argument("--parts-c", type=int, default=2)
    p.add_argument("--threshold", type=float, default=0.85)
    sub.add_parser("apply")
    for s in sub.choices.values():
        s.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    if args.cmd == "prep":
        prep(Path(args.out), args.parts_b, args.parts_c, args.threshold)
    else:
        apply_cli(Path(args.out))


if __name__ == "__main__":
    main()
