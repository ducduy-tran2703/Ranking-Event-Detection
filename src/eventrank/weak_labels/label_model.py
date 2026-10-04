"""Gộp phiếu của các hàm gán nhãn (LF) thành xác suất — mô hình Dawid–Skene nhị phân, học bằng EM.

Không cần nhãn thật: mô hình ước lượng độ chính xác của từng LF từ việc các LF đồng thuận / mâu thuẫn
với nhau (cùng ý tưởng với `LabelModel` của Snorkel, viết lại bằng numpy để khỏi kéo theo PyTorch).

Phiếu: 1 = cùng sự kiện, 0 = khác sự kiện, ABSTAIN (-1) = bỏ qua.
Mỗi LF j có ma trận nhầm lẫn P(phiếu | y) trên ba giá trị {0, 1, bỏ qua}. Xác suất bỏ qua được phép
khác nhau giữa hai lớp (như Snorkel): LF chỉ bỏ phiếu dương mà im lặng là bằng chứng yếu cho lớp âm.

Hai chốt chặn (gặp trên dữ liệu thật — EM coi "các LF âm cùng im lặng" là lớp dương):
  - `prior` cố định (như `class_balance` của Snorkel) thay vì để EM tự học.
  - cặp không có phiếu dương nào bị chặn ở p ≤ 0.5: không có bằng chứng dương thì không là cặp dương.
"""
from __future__ import annotations

import numpy as np

ABSTAIN = -1
_EPS = 1e-6


class LabelModel:
    def __init__(self, n_iter: int = 200, tol: float = 1e-7, smoothing: float = 1.0,
                 prior: float | None = None):
        self.n_iter = n_iter
        self.tol = tol
        self.smoothing = smoothing
        self.fixed_prior = prior
        self.prior: float = 0.5 if prior is None else prior
        self.theta: np.ndarray | None = None      # (n_lf, 2 lớp y, 3 giá trị phiếu)

    @staticmethod
    def _onehot(L: np.ndarray) -> np.ndarray:
        idx = np.where(L == ABSTAIN, 2, L).astype(int)          # 0, 1, 2=bỏ qua
        return np.eye(3)[idx]                                    # (n, m, 3)

    def _posterior(self, V: np.ndarray) -> np.ndarray:
        logt = np.log(self.theta + _EPS)                         # (m, 2, 3)
        ll = np.einsum("nmv,myv->ny", V, logt)
        ll += np.log([1 - self.prior + _EPS, self.prior + _EPS])
        ll -= ll.max(axis=1, keepdims=True)
        p = np.exp(ll)
        return p[:, 1] / p.sum(axis=1)

    def fit(self, L: np.ndarray) -> LabelModel:
        V = self._onehot(L)
        # Khởi tạo bằng bỏ phiếu đa số
        pos, neg = (L == 1).sum(1), (L == 0).sum(1)
        q = np.where(pos + neg > 0, (pos + 0.5) / (pos + neg + 1.0), 0.5)
        prev = None
        for _ in range(self.n_iter):
            # M-step
            w = np.stack([1 - q, q], axis=1)                     # (n, 2)
            counts = np.einsum("ny,nmv->myv", w, V) + self.smoothing
            self.theta = counts / counts.sum(axis=2, keepdims=True)
            if self.fixed_prior is None:
                self.prior = float(np.clip(q.mean(), 0.01, 0.99))
            # E-step
            q = self._posterior(V)
            ll = float(q.sum())
            if prev is not None and abs(ll - prev) < self.tol * len(q):
                break
            prev = ll
        return self

    def predict_proba(self, L: np.ndarray) -> np.ndarray:
        if self.theta is None:
            raise RuntimeError("Chưa fit")
        p = self._posterior(self._onehot(L))
        return np.where((L == 1).any(axis=1), p, np.minimum(p, 0.5))

    def accuracies(self) -> np.ndarray:
        """Độ chính xác ước lượng của từng LF khi nó bỏ phiếu: P(phiếu = y | có phiếu)."""
        t = self.theta
        right = (1 - self.prior) * t[:, 0, 0] + self.prior * t[:, 1, 1]
        voted = (1 - self.prior) * (t[:, 0, 0] + t[:, 0, 1]) + self.prior * (t[:, 1, 0] + t[:, 1, 1])
        return right / np.maximum(voted, _EPS)
