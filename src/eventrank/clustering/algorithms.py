"""Thuật toán gom cụm sự kiện. Chỉ cần vector (đã chuẩn hoá L2, cosine = tích vô hướng) và thời gian đăng (giây).

- `single_pass`: duyệt bài theo thời gian; bài vào cụm có cosine TRUNG BÌNH với các thành viên cao nhất nếu ≥ ngưỡng
  (cụm không có bài mới quá `window_hours` thì "nguội"), không thì mở cụm mới. Dùng cho gán nhanh khi chạy thật.
- `agglo_tree` + `agglo_cut`: agglomerative average-linkage trên một ma trận cosine đầy đủ; cặp cách nhau > cửa sổ coi như
  rất xa (khoảng cách 2). Cần ma trận N × N → chỉ dùng cho tập nhỏ (tập vàng 1.496 bài).
- `agglo_components`: CÙNG kết quả với agglo_tree + agglo_cut nhưng chạy được trên cả kho (hàng chục nghìn bài).

Vì sao `agglo_components` cho kết quả y hệt: average-linkage chỉ gộp hai cụm khi cosine TRUNG BÌNH giữa chúng ≥ ngưỡng,
mà trung bình ≥ ngưỡng thì phải có ít nhất một cặp ≥ ngưỡng (và cặp đó cách nhau ≤ cửa sổ, không thì khoảng cách là 2).
Vậy mọi cụm cuối cùng nằm gọn trong một thành phần liên thông của đồ thị "cosine ≥ ngưỡng VÀ cách nhau ≤ cửa sổ"; hai
thành phần khác nhau không bao giờ được gộp. Chạy agglo riêng trong từng thành phần = chạy trên cả kho.
Đã kiểm chứng: test `test_agglo_components_giong_het_agglo_day_du` + chạy lại tập vàng ra đúng nhãn của cluster_eval.
"""
from __future__ import annotations

import numpy as np

WINDOW_HOURS = 48


def single_pass(S: np.ndarray, times: np.ndarray, th: float, window_hours: float = WINDOW_HOURS) -> np.ndarray:
    n = len(times)
    lab = np.full(n, -1)
    csum = np.zeros((n, n), dtype=np.float32)                        # cột c = tổng S[:, thành viên cụm c]
    size, last = [], []
    for i in np.argsort(times, kind="stable"):
        k = len(size)
        if k:
            score = csum[i, :k] / np.array(size)
            score[times[i] - np.array(last) > window_hours * 3600] = -1     # cụm đã "nguội"
            c = int(np.argmax(score))
            if score[c] >= th:
                lab[i] = c
                csum[:, c] += S[:, i]
                size[c] += 1
                last[c] = max(last[c], times[i])
                continue
        lab[i] = k
        csum[:, k] = S[:, i]
        size.append(1)
        last.append(times[i])
    return lab


def agglo_tree(S: np.ndarray, times: np.ndarray, window_hours: float = WINDOW_HOURS) -> np.ndarray:
    """Cây average-linkage (dựng một lần, cắt nhiều ngưỡng). Cặp cách nhau > cửa sổ: khoảng cách 2 (rất xa)."""
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform

    D = 1.0 - S
    D[np.abs(times[:, None] - times[None, :]) > window_hours * 3600] = 2.0
    np.fill_diagonal(D, 0)
    return linkage(squareform(np.clip((D + D.T) / 2, 0, None), checks=False), method="average")


def agglo_cut(Z: np.ndarray, th: float) -> np.ndarray:
    from scipy.cluster.hierarchy import fcluster

    return fcluster(Z, t=1.0 - th, criterion="distance")


def components(E: np.ndarray, times: np.ndarray, th: float, window_hours: float = WINDOW_HOURS,
               block: int = 2048) -> np.ndarray:
    """Nhãn thành phần liên thông của đồ thị (cosine ≥ th VÀ |Δt| ≤ cửa sổ). Tính theo khối trên thứ tự thời gian:
    mỗi khối chỉ so với các bài trong cửa sổ phía sau nó → bộ nhớ O(block × số bài trong cửa sổ)."""
    n = len(times)
    order = np.argsort(times, kind="stable")
    t, X = times[order], E[order]
    parent = np.arange(n)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    win = window_hours * 3600
    for a in range(0, n, block):
        b = min(a + block, n)
        hi = int(np.searchsorted(t, t[b - 1] + win, side="right"))  # cột: từ a đến hết cửa sổ của bài cuối khối
        S = X[a:b] @ X[a:hi].T
        ok = (S >= th) & (np.abs(t[a:b, None] - t[None, a:hi]) <= win)
        for i, j in zip(*np.nonzero(ok), strict=True):
            u, v = a + i, a + j
            if u < v:
                ru, rv = find(u), find(v)
                if ru != rv:
                    parent[max(ru, rv)] = min(ru, rv)
    comp = np.array([find(i) for i in range(n)])
    out = np.empty(n, dtype=np.int64)
    out[order] = comp
    return out


def agglo_components(E: np.ndarray, times: np.ndarray, th: float, window_hours: float = WINDOW_HOURS,
                     max_component: int = 8000) -> tuple[np.ndarray, dict]:
    """(nhãn cụm 0..k−1, thống kê). Agglo average-linkage cắt ở ngưỡng th, chạy riêng trong từng thành phần liên thông.
    Thành phần > max_component bài → báo lỗi (ma trận quá lớn) thay vì âm thầm làm khác đi."""
    comp = components(E, times, th, window_hours)
    labels = np.full(len(times), -1, dtype=np.int64)
    sizes = np.bincount(comp)
    nxt = 0
    for c in np.nonzero(sizes)[0]:
        idx = np.nonzero(comp == c)[0]
        if len(idx) == 1:
            labels[idx] = nxt
            nxt += 1
            continue
        if len(idx) > max_component:
            raise ValueError(f"thành phần liên thông {len(idx)} bài > {max_component}: tăng ngưỡng hoặc max_component")
        sub = agglo_cut(agglo_tree(E[idx] @ E[idx].T, times[idx], window_hours), th)
        labels[idx] = nxt + sub - 1                                   # fcluster đánh số từ 1
        nxt += int(sub.max())
    multi = sizes[sizes > 1]
    return labels, {"n_components_multi": len(multi), "largest_component": int(sizes.max()),
                    "n_clusters": nxt}
