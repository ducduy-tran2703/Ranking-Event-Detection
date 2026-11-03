"""Biến bài báo thành vector (đã chuẩn hoá L2) bằng mô hình sentence-transformers, có lưu đệm theo `article_id`.

Văn bản đầu vào = `tiêu đề. sapo` (giống lúc fine-tune). Tiền xử lý PHẢI giống lúc train:
`pyvi` = NFC + tách từ (bkai), `query` = NFC + "query: " (e5), `raw` = chỉ NFC.

Lưu đệm: một file .npz (`ids`, `E`, `path`, `prep`). Chạy lại chỉ encode bài mới; bị ngắt giữa chừng thì phần đã encode
vẫn còn (ghi sau mỗi lô `chunk` bài). Đổi mô hình hoặc tiền xử lý → đệm cũ bị bỏ qua. Trường `path` lưu `cache_key`
(mặc định = đường dẫn mô hình; pipeline dùng `model_version` để file encode trên Kaggle — training/encode_silver_kaggle.ipynb
— dùng được ở máy khác).
"""
from __future__ import annotations

import gc
import unicodedata
from collections.abc import Callable
from pathlib import Path

import numpy as np


def head_text(title: str, sapo: str) -> str:
    return f"{title}. {sapo}".strip(" .") if sapo else title


def prep(text: str, how: str) -> str:
    t = unicodedata.normalize("NFC", text)
    if how == "pyvi":
        from pyvi import ViTokenizer
        return ViTokenizer.tokenize(t)
    return "query: " + t if how == "query" else t


def _load_cache(path: Path, key: str, how: str) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    z = np.load(path, allow_pickle=True)
    if str(z["path"]) != key or str(z.get("prep", how)) != how:
        return {}
    return dict(zip(z["ids"].tolist(), z["E"], strict=True))


def _save_cache(path: Path, vecs: dict[str, np.ndarray], key: str, how: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = sorted(vecs)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, ids=np.array(ids), E=np.stack([vecs[i] for i in ids]).astype(np.float32), path=key, prep=how)
    tmp.replace(path)


def encode(texts: dict[str, str], model_path: str, how: str, cache: str | Path | None = None,
           cache_key: str | None = None, chunk: int = 2000, batch_size: int = 16, max_seq_length: int = 256,
           encoder: Callable[[list[str]], np.ndarray] | None = None,
           log: Callable[[str], None] = print) -> dict[str, np.ndarray]:
    """{article_id: văn bản thô} → {article_id: vector}. `encoder` (danh sách văn bản đã tiền xử lý → ma trận đã chuẩn
    hoá) chỉ để test; mặc định nạp SentenceTransformer trên CPU."""
    cache = Path(cache) if cache else None
    key = cache_key or model_path
    vecs = _load_cache(cache, key, how) if cache else {}
    todo = [i for i in texts if i not in vecs]
    if todo:
        log(f"encode {len(todo)} bài (đã có {len(vecs)} trong đệm) bằng {model_path} ({how})…")
        model = None
        if encoder is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_path, device="cpu")
            model.max_seq_length = max_seq_length
            encoder = lambda xs: model.encode(xs, batch_size=batch_size, normalize_embeddings=True,
                                              show_progress_bar=False)
        for k in range(0, len(todo), chunk):
            part = todo[k:k + chunk]
            E = np.asarray(encoder([prep(texts[i], how) for i in part]), dtype=np.float32)
            vecs.update(zip(part, E, strict=True))
            if cache:
                _save_cache(cache, vecs, key, how)
            log(f"  {min(k + chunk, len(todo))}/{len(todo)}")
        del model
        gc.collect()                                                 # máy 7,6 GB: không giữ mô hình sau khi xong
    return {i: vecs[i] for i in texts}
