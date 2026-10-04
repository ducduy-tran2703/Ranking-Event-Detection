"""Các hàm gán nhãn (labeling functions) cho cặp bài: 1 = cùng sự kiện, 0 = khác, -1 = bỏ qua.

Mỗi LF dựa trên MỘT loại bằng chứng. Không LF nào dùng "cùng chuyên mục" làm phiếu dương, vì cùng một
sự kiện thường nằm ở chuyên mục khác nhau giữa các báo (phan-tich-event-clustering-trending.md §3.1).

Ngưỡng ban đầu chọn theo phân bố đặc trưng; chỉnh lại sau khi đo trên tập cặp gán tay (audit_sample.csv).
"""
from __future__ import annotations

import numpy as np

from eventrank.weak_labels.label_model import ABSTAIN

POS_MAX_HOURS = 72      # phiếu dương chỉ khi hai bài cách nhau ≤ 3 ngày: xa hơn thường là diễn biến khác


def _vote(pos: np.ndarray, neg: np.ndarray | None = None) -> np.ndarray:
    v = np.full(len(pos), ABSTAIN)
    if neg is not None:
        v[neg] = 0
    v[pos] = 1
    return v


def lf_repost(f):
    """Bài đăng lại (cùng tiêu đề / sapo) → chắc chắn cùng sự kiện."""
    return _vote(f["same_dup"] > 0)


def _near(f):
    return f["dt_hours"] <= POS_MAX_HOURS


def lf_entity_overlap(f):
    """Thực thể chung có trọng số (nổi bật × IDF), chuẩn hoá theo hợp — bài dài không được lợi."""
    return _vote((f["ent_wjacc"] >= 0.30) & (f["ent_score"] >= 10) & _near(f),
                 f["ent_wjacc"] < 0.04)


def lf_head_entities(f):
    """≥ 2 thực thể hiếm cùng nằm ở tiêu đề/sapo của cả hai bài."""
    return _vote((f["n_head_shared"] >= 2) & _near(f))


def lf_lexical(f):
    """Tương đồng từ vựng TF-IDF (tiêu đề + sapo, hoặc thêm đoạn đầu).

    v1 có hai LF riêng cho cos_head và cos_lead; chúng bỏ phiếu giống nhau 75% số lần, nên label model đếm
    một tín hiệu hai lần và tự tin quá mức. v2 gộp làm một.
    """
    return _vote(((f["cos_head"] >= 0.45) | (f["cos_lead"] >= 0.40)) & _near(f),
                 (f["cos_head"] < 0.06) & (f["cos_lead"] < 0.08))


DENSE_POS = 0.80        # ngưỡng cosine — phụ thuộc mô hình; chỉnh trên tập chỉnh, đặt qua set_dense_thresholds()
DENSE_NEG = 0.30


def set_dense_thresholds(pos: float, neg: float) -> None:
    global DENSE_POS, DENSE_NEG
    DENSE_POS, DENSE_NEG = pos, neg


def lf_dense(f):
    """Tương đồng ngữ nghĩa (embedding zero-shot) của tiêu đề + sapo. Bỏ qua nếu chưa có embedding.

    MiniLM (paraphrase-multilingual-MiniLM-L12-v2) trên 399 cặp chỉnh: cos ≥ 0,80 → precision 0,80;
    cos < 0,30 → 0/76 cặp là cùng sự kiện.
    """
    c = np.nan_to_num(f["cos_dense"], nan=-np.inf)
    neg = np.nan_to_num(f["cos_dense"], nan=np.inf) < DENSE_NEG
    return _vote((c >= DENSE_POS) & _near(f), neg)


def lf_shared_number(f):
    """Cùng một con số cụ thể ("15 người", "2,5 tỷ") + có chung ít nhất vài thực thể."""
    return _vote((f["n_numbers"] >= 1) & (f["ent_score"] >= 3) & _near(f))


def veto_dated_series(f):
    """Hai tiêu đề cùng ghi ngày nhưng khác ngày ("Giá Bitcoin hôm nay 7.9" / "… 8.9") → khác sự kiện.

    Là luật PHỦ QUYẾT, không phải một phiếu: chuỗi bài theo ngày có tiêu đề gần như y hệt nhau, nên các
    LF TF-IDF bỏ phiếu dương rất mạnh và label model sẽ coi LF này là "kém" rồi bỏ qua nó (đã gặp: độ
    chính xác ước lượng 0,31). Ở đúng loại cặp này, ngày tháng đúng còn TF-IDF sai.
    """
    return f["date_conflict"] > 0


def lf_time_far(f):
    """Cách nhau > POS_MAX_HOURS → coi như diễn biến/sự kiện khác."""
    return _vote(np.zeros(len(f["dt_hours"]), bool), f["dt_hours"] > POS_MAX_HOURS)


def lf_category_mismatch(f):
    """Khác chuyên mục VÀ gần như không chung thực thể → khác sự kiện (chỉ dùng cho phiếu âm)."""
    return _vote(np.zeros(len(f["dt_hours"]), bool),
                 (f["same_category"] == 0) & (f["ent_wjacc"] < 0.12))


LFS = [lf_repost, lf_entity_overlap, lf_head_entities, lf_lexical, lf_dense,
       lf_shared_number, lf_time_far, lf_category_mismatch]
# Nhóm bằng chứng: hai LF cùng nhóm KHÔNG được tính là hai bằng chứng độc lập
FAMILY = {"lf_repost": "repost", "lf_entity_overlap": "entity", "lf_head_entities": "entity",
          "lf_lexical": "lexical", "lf_dense": "semantic", "lf_shared_number": "number"}


def positive_families(L: np.ndarray) -> np.ndarray:
    """Số NHÓM bằng chứng có ít nhất một phiếu dương, cho từng cặp."""
    names = [lf.__name__ for lf in LFS]
    fams = sorted(set(FAMILY.values()))
    cols = [np.any(L[:, [k for k, n in enumerate(names) if FAMILY.get(n) == fam]] == 1, axis=1)
            for fam in fams]
    return np.sum(cols, axis=0)


def only_semantic(L: np.ndarray) -> np.ndarray:
    """Cặp mà bằng chứng dương DUY NHẤT là tương đồng ngữ nghĩa.

    Đo trên 45 cặp như vậy (Claude gán mù): chỉ 58% cùng sự kiện — embedding nhận ra "cùng chủ đề / cùng khuôn
    tin" (điểm chuẩn của hai trường khác nhau, sắp xếp trường ở hai phường) chứ không phải "cùng sự kiện".
    """
    names = [lf.__name__ for lf in LFS]
    pos = L == 1
    sem = np.array([FAMILY.get(n) == "semantic" for n in names])
    return pos[:, sem].any(axis=1) & ~pos[:, ~sem].any(axis=1)


def veto_title_doc(f):
    """Mỗi tiêu đề nêu một văn bản mà bài kia không hề nhắc ("Luật Hòa giải" ↔ "Luật Phát triển đô thị")."""
    return f["conflict_doc"] > 0


VETOES = [veto_dated_series, veto_title_doc]
VETO_P = 0.02           # xác suất gán cho cặp bị phủ quyết


def apply_lfs(features: dict) -> np.ndarray:
    return np.stack([lf(features) for lf in LFS], axis=1)


def veto_mask(features: dict) -> np.ndarray:
    mask = np.zeros(len(features["dt_hours"]), bool)
    for v in VETOES:
        mask |= v(features)
    return mask


def apply_vetoes(features: dict, p: np.ndarray) -> np.ndarray:
    return np.where(veto_mask(features), np.minimum(p, VETO_P), p)
