"""Đóng gói dữ liệu để fine-tune embedding trên Kaggle → data/temp/kaggle_upload/ (tải thư mục này lên Kaggle Dataset).

    .venv/bin/python training/prepare_kaggle_data.py

Đầu vào (đều nằm trên máy, không gọi mạng):
    data/temp/weak_supervision/weak_supervision_pairs.csv   cặp nhãn yếu bản tạm, tải từ R2 gold/weak_supervision/
    data/weak_labels/v3/train_triplets.jsonl               bộ ba nhãn yếu v3 (anchor, positive, negative khó)
    data/weak_labels/v3/train_pairs.jsonl                  cặp có điểm mềm p của v3 (cho CoSENT)
    data/weak_labels/v3/articles.jsonl                     văn bản "tiêu đề. sapo" của mọi bài (Article.head_text)
    data/weak_labels/v1/audit_labeled_llm_ids.csv          tập CHỈNH (chọn ngưỡng), nhãn Claude
    data/weak_labels/v2/audit_labeled_llm.csv              tập ĐO (holdout), nhãn Claude
    data/weak_labels/v2/pairs.jsonl                        tổng thể để tính trọng số tầng + cos_head của cặp đo
    data/weak_labels/v3/pairs.jsonl                        nguồn của bộ dò "cùng câu chuyện, khác sự kiện"
    data/weak_labels/v4/graded_pairs.jsonl                 (nếu có) cặp 4 mức liên quan — `graded build`
    data/weak_labels/v4/test_labeled.csv + test_ids.csv    (nếu có) tập đo 4 mức (holdout, nhãn Claude)

Đầu ra: weak_supervision_pairs.csv, v3_triplets.csv, v3_pairs.csv, articles.jsonl (MỌI bài — bể truy hồi của dev
cần đủ bài cùng thời gian), audit_v1.csv, audit_v2.csv, strata_sizes.json, probe_story.csv, README.md, và nếu đã có
nhãn yếu v4: v4_pairs.csv, v4_test.csv, v4_test_strata.json.
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path

from eventrank.weak_labels.evaluate import bin_of

PAIRS = Path("data/temp/weak_supervision/weak_supervision_pairs.csv")
WL = Path("data/weak_labels")
OUT = Path("data/temp/kaggle_upload")

# Bộ dò: cặp nhãn yếu chắc chắn âm (p < 0,1) nhưng trùng tiêu đề khá (cos_head > 0,3) và có xung đột ngày / tổ chức /
# địa điểm / nhân vật / sự kiện — "Giá vàng 14/9" ↔ "15/9", "kiểm tra Ban Thường vụ A" ↔ "… Ban Thường vụ B".
# Chỉ lấy cặp có CẢ HAI bài trong holdout → không bài nào từng xuất hiện trong dữ liệu train (notebook cắt train
# trước holdout − 48h). Luật chưa được kiểm bằng nhãn: dùng để so trước/sau fine-tune, không làm nhãn vàng.
PROBE_MAX_P, PROBE_MIN_COS_HEAD = 0.1, 0.3
CONFLICTS = ("conflict_event", "conflict_loc", "conflict_org", "conflict_per")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(PAIRS, OUT / PAIRS.name)
    with open(PAIRS, encoding="utf-8-sig") as f:
        n_pairs = sum(1 for _ in csv.DictReader(f))

    with open(WL / "v3/train_triplets.jsonl", encoding="utf-8") as f, \
            open(OUT / "v3_triplets.csv", "w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(["anchor_id", "positive_id", "negative_id", "p"])
        n_tri = 0
        for line in f:
            t = json.loads(line)
            w.writerow([t["anchor_id"], t["positive_id"], t.get("negative_id") or "", t["p"]])
            n_tri += 1
    with open(WL / "v3/train_pairs.jsonl", encoding="utf-8") as f, \
            open(OUT / "v3_pairs.csv", "w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(["a", "b", "label", "score"])
        n_v3p = 0
        for line in f:
            r = json.loads(line)
            w.writerow([r["a_id"], r["b_id"], r["label"], r["score"]])
            n_v3p += 1

    with open(WL / "v1/audit_labeled_llm_ids.csv", encoding="utf-8-sig") as f:
        v1 = [r for r in csv.DictReader(f) if r["label_llm"].strip() in ("0", "1")]
    with open(WL / "v2/audit_labeled_llm.csv", encoding="utf-8-sig") as f:
        v2 = [r for r in csv.DictReader(f) if r["label_llm"].strip() in ("0", "1")]

    # Tổng thể của tập đo = cặp ứng viên holdout của v2, trừ các cặp tập chỉnh (giống evaluate.py)
    excl = {frozenset((r["a"], r["b"])) for r in v1}
    v2_keys = {frozenset((r["a"], r["b"])) for r in v2}
    sizes: Counter[str] = Counter()
    cos_head: dict[frozenset, float] = {}
    with open(WL / "v2/pairs.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            k = frozenset((r["a"], r["b"]))
            if r["split"] == "holdout" and k not in excl:
                sizes[f"{bin_of(r['p'])}|{int(r['cross_source'])}"] += 1
            if k in v2_keys:
                cos_head[k] = r["cos_head"]
    assert len(cos_head) == len(v2_keys), "thiếu cos_head cho một số cặp của tập đo"

    probe = []
    with open(WL / "v3/pairs.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["split"] != "holdout" or r["p"] >= PROBE_MAX_P or r["cos_head"] <= PROBE_MIN_COS_HEAD:
                continue
            if frozenset((r["a"], r["b"])) in v2_keys | excl:
                continue
            if r["date_conflict"]:
                probe.append([r["a"], r["b"], "date_series", r["cos_head"]])
            elif any(r[c] for c in CONFLICTS):
                probe.append([r["a"], r["b"], "conflict", r["cos_head"]])

    n_art = 0
    with open(WL / "v3/articles.jsonl", encoding="utf-8") as f, \
            open(OUT / "articles.jsonl", "w", encoding="utf-8") as out:
        for line in f:
            a = json.loads(line)
            keep = {k: a[k] for k in ("article_id", "source", "category", "published_at", "text")}
            out.write(json.dumps(keep, ensure_ascii=False) + "\n")
            n_art += 1

    with open(OUT / "audit_v1.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a", "b", "label_llm"])
        w.writerows([r["a"], r["b"], r["label_llm"].strip()] for r in v1)
    with open(OUT / "audit_v2.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a", "b", "p_bin", "cross_source", "label_llm", "cos_head"])
        w.writerows([r["a"], r["b"], r["p_bin"], r["cross_source"], r["label_llm"].strip(),
                     cos_head[frozenset((r["a"], r["b"]))]] for r in v2)
    with open(OUT / "probe_story.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a", "b", "kind", "cos_head"])
        w.writerows(probe)
    n_v4 = _export_v4()
    (OUT / "strata_sizes.json").write_text(json.dumps(dict(sizes), indent=2), encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")
    kinds = Counter(p[2] for p in probe)
    print(f"tạm {n_pairs} cặp · v3 {n_tri} bộ ba, {n_v3p} cặp mềm · {n_art} bài · tập chỉnh {len(v1)} · "
          f"tập đo {len(v2)} · tổng thể {sum(sizes.values())} cặp · bộ dò {len(probe)} cặp {dict(kinds)} · "
          f"v4 {n_v4} → {OUT}/")


def _recheck_labels(v4: Path) -> dict[tuple[str, str], str]:
    """Nhãn gán lại theo quy tắc 29/10 (graded recheck, rồi graded consistency → recheck2…4, retest, audit_train,
    retrain; tập sau đè tập trước), khoá cả hai chiều (a, b) và (b, a)."""
    out = {}
    for name in ("recheck", "recheck2", "recheck3", "recheck4", "retest", "audit_train", "retrain"):
        if not (v4 / f"{name}_labeled.csv").exists():
            continue
        with open(v4 / f"{name}_ids.csv", encoding="utf-8") as f:
            ids = {r["pair_no"]: r for r in csv.DictReader(f)}
        with open(v4 / f"{name}_labeled.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                i, lv = ids[r["pair_no"]], r["level"].strip().lower()
                if lv in ("0", "1", "2", "3", "x"):
                    out[(i["a"], i["b"])] = out[(i["b"], i["a"])] = lv
    return out


def _manual_labels(v4: Path) -> dict[tuple[str, str], str]:
    """manual_overrides.csv: nhãn người dùng quyết định trực tiếp, khoá cả hai chiều."""
    if not (v4 / "manual_overrides.csv").exists():
        return {}
    out = {}
    with open(v4 / "manual_overrides.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["level"].strip() in ("0", "1", "2", "3"):
                out[(r["a"], r["b"])] = out[(r["b"], r["a"])] = r["level"].strip()
    return out


def _export_v4() -> str:
    v4 = WL / "v4"
    if not (v4 / "graded_pairs.jsonl").exists():
        return "chưa có (chạy `graded build`)"
    with open(v4 / "graded_pairs.jsonl", encoding="utf-8") as f, \
            open(OUT / "v4_pairs.csv", "w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(["a", "b", "level", "score", "source"])
        n_train = 0
        for line in f:
            r = json.loads(line)
            w.writerow([r["a_id"], r["b_id"], r["level"], r["score"], r["source"]])
            n_train += 1
    # Tập đo = test + test2 (holdout, nhãn Claude); cặp người đã duyệt (human_label_100) dùng NHÃN NGƯỜI
    test: dict[tuple[str, str], list] = {}
    for name in ("test", "test2"):
        if not (v4 / f"{name}_labeled.csv").exists():
            continue
        with open(v4 / f"{name}_ids.csv", encoding="utf-8") as f:
            ids = {r["pair_no"]: r for r in csv.DictReader(f)}
        with open(v4 / f"{name}_labeled.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["level"].strip() in ("0", "1", "2", "3"):
                    i = ids[r["pair_no"]]
                    test[(i["a"], i["b"])] = [i["bucket"], r["level"].strip(), "claude"]
    recheck = _recheck_labels(v4)                     # gán lại theo quy tắc 29/10: đè nhãn Claude, không đè nhãn người
    for key, lv in recheck.items():
        if key in test:
            test[key][1:] = [lv, "claude"] if lv != "x" else test[key][1:]
    test = {k: v for k, v in test.items() if recheck.get(k) != "x"}
    n_human = 0
    if (v4 / "human_label_100.csv").exists():
        with open(v4 / "human_label_100_ids.csv", encoding="utf-8") as f:
            hid = {r["pair_no"]: r for r in csv.DictReader(f)}
        with open(v4 / "human_label_100.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                i, lv = hid[r["pair_no"]], (r.get("level_human") or "").strip()
                key = (i["a"], i["b"])
                if key in test and lv in ("0", "1", "2", "3"):
                    test[key][1:] = [lv, "human"]
                    n_human += 1
                elif key in test and lv.lower() == "x":
                    del test[key]
    manual = _manual_labels(v4)                       # người dùng quyết định trực tiếp: đè mọi nguồn khác
    for key, lv in manual.items():
        if key in test:
            test[key][1:] = [lv, "human"]
    if test:
        with open(OUT / "v4_test.csv", "w", encoding="utf-8", newline="") as out:
            w = csv.writer(out)
            w.writerow(["a", "b", "bucket", "level", "source"])
            w.writerows([a, b, *v] for (a, b), v in test.items())
        shutil.copy(v4 / "test_strata_sizes.json", OUT / "v4_test_strata.json")
    n_test = f"{len(test)} ({n_human} nhãn người)"
    # Tập đo riêng cho cặp "cùng nội dung, khác chữ" (graded.hard_mask) — không gộp vào v4_test vì lấy mẫu dồn
    # vào vùng khó, sẽ làm lệch các chỉ số chung
    if (v4 / "hardtest_labeled.csv").exists():
        with open(v4 / "hardtest_ids.csv", encoding="utf-8") as f:
            hid2 = {r["pair_no"]: r for r in csv.DictReader(f)}
        with open(v4 / "hardtest_labeled.csv", encoding="utf-8-sig") as f, \
                open(OUT / "v4_test_hard.csv", "w", encoding="utf-8", newline="") as out:
            w = csv.writer(out)
            w.writerow(["a", "b", "level"])
            rows = []
            for r in csv.DictReader(f):
                a, b = hid2[r["pair_no"]]["a"], hid2[r["pair_no"]]["b"]
                lv = manual.get((a, b), recheck.get((a, b), r["level"].strip()))
                if lv in ("0", "1", "2", "3"):
                    rows.append((a, b, lv))
            w.writerows(rows)
        n_test += f", khác chữ {len(rows)}"
    return f"{n_train} cặp train, {n_test} cặp đo"


README = """# Dữ liệu fine-tune embedding

| File | Nội dung |
|---|---|
| `weak_supervision_pairs.csv` | cặp nhãn yếu **bản tạm** (`article_1_id, article_2_id, similarity_score, label`), từ R2 `gold/weak_supervision/` — nhãn kiểu "cùng chủ đề", chỉ để đối chứng |
| `v3_triplets.csv` | bộ ba nhãn yếu **v3** (`anchor_id, positive_id, negative_id, p`); `negative_id` rỗng khi không tìm được negative khó |
| `v3_pairs.csv` | cặp v3 có điểm mềm (`a, b, label, score`), `score` = p đã hiệu chỉnh — cho CoSENT |
| `articles.jsonl` | mọi bài: `article_id, source, category, published_at, text` — `text` = tiêu đề + ". " + sapo |
| `audit_v1.csv` | tập CHỈNH (399 cặp, nhãn Claude) — chỉ dùng để chọn ngưỡng cosine |
| `audit_v2.csv` | tập ĐO (400 cặp holdout, nhãn Claude) — chỉ dùng để đo; `cos_head` = TF-IDF tiêu đề, để chia tầng |
| `strata_sizes.json` | số cặp mỗi tầng trong tổng thể → trọng số Horvitz–Thompson khi đo |
| `probe_story.csv` | bộ dò "cùng câu chuyện / cùng khuôn tin, khác sự kiện" trong holdout (luật, chưa kiểm bằng nhãn) |
| `v4_pairs.csv` | (nếu có) cặp train 4 mức: `a, b, level (3/2/1/0), score (1/0,6/0,3/0), source (rule/claude)` |
| `v4_test_hard.csv` | (nếu có) tập đo riêng 4 mức cho cặp **cùng nội dung, khác chữ** trong holdout (nhãn Claude) |
| `v4_test.csv`, `v4_test_strata.json` | (nếu có) tập đo 4 mức trong holdout (test + test2), nhãn Claude; cặp người đã duyệt dùng nhãn người (`source = human`); kèm kích thước tầng để tính trọng số |

Nhãn đối chiếu là của Claude, chưa phải người. Dataset này để chế độ riêng tư.
"""

if __name__ == "__main__":
    main()
