"""B-Cubed: chấm một cách gom cụm so với đáp án (Bagga & Baldwin 1998; Amigó et al. 2009).

Với mỗi bài i:
    precision(i) = |cụm dự đoán của i ∩ cụm vàng của i| / |cụm dự đoán của i|
    recall(i)    = |cụm dự đoán của i ∩ cụm vàng của i| / |cụm vàng của i|
rồi lấy trung bình trên mọi bài. Khác purity/NMI: gộp hết vào một cụm không được điểm cao (precision tụt), tách
mỗi bài một cụm cũng không (recall tụt). Đây là chỉ số chính để so các mô hình embedding (AGENTS.md mục 4).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Mapping


def bcubed(pred: Mapping[Hashable, Hashable], gold: Mapping[Hashable, Hashable]) -> tuple[float, float, float]:
    """(precision, recall, F1) trên các bài có mặt ở CẢ HAI cách gom. Nhãn cụm chỉ cần phân biệt, không cần khớp tên."""
    items = [i for i in pred if i in gold]
    if not items:
        raise ValueError("hai cách gom không có bài chung")
    n_pred = Counter(pred[i] for i in items)
    n_gold = Counter(gold[i] for i in items)
    n_both = Counter((pred[i], gold[i]) for i in items)
    p = sum(n_both[pred[i], gold[i]] / n_pred[pred[i]] for i in items) / len(items)
    r = sum(n_both[pred[i], gold[i]] / n_gold[gold[i]] for i in items) / len(items)
    return p, r, 2 * p * r / (p + r)
