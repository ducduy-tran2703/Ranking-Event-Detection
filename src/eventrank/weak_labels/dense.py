"""Embedding zero-shot của tiêu đề + sapo, làm TÍN HIỆU NGỮ NGHĨA cho nhãn yếu.

Hai cách chạy:

    # 1) Mô hình ONNX int8 nhỏ (mặc định, ~135 MB) — tự tải, tự nối lại khi đứt, kiểm SHA-256 — make embed
    uv run --group embed python -m eventrank.weak_labels.dense
    uv run --group embed python -m eventrank.weak_labels.dense --model Xenova/bge-m3      # ~590 MB, mạnh hơn

    # 2) Mô hình đầy đủ qua sentence-transformers (tự tải từ Hugging Face, bge-m3 ~2,3 GB)
    uv run --group embed python -m eventrank.weak_labels.dense --model BAAI/bge-m3

Ghi ra data/weak_labels/cache/<tên-mô-hình>.npz (article_id + vector đã chuẩn hoá L2). `build --dense-model`
đọc file này; nếu không có thì LF ngữ nghĩa bỏ qua mọi cặp.

Chọn mô hình KHÁC HỌ với hai mô hình sẽ fine-tune (PhoBERT, multilingual-e5): nếu dùng chính e5 để sinh nhãn
rồi fine-tune e5 trên nhãn đó, mô hình chỉ học lại độ tương đồng nó đã có sẵn.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

DEFAULT_MODEL = "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_MODELS = "data/weak_labels/models"
# Mô hình ONNX tải được trực tiếp: tệp → SHA-256 do Hugging Face công bố ("" = tệp nhỏ, không kiểm)
ONNX_MODELS = {
    "Xenova/paraphrase-multilingual-MiniLM-L12-v2": {
        "config.json": "", "tokenizer_config.json": "", "special_tokens_map.json": "",
        "tokenizer.json": "b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441",
        "onnx/model_quantized.onnx": "66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc",
    },
    "Xenova/bge-m3": {
        "config.json": "", "tokenizer_config.json": "", "special_tokens_map.json": "",
        "tokenizer.json": "6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790",
        "onnx/model_quantized.onnx": "0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d",
    },
}


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_model(repo: str, root: str | Path = LOCAL_MODELS, attempts: int = 100,
                   files: dict[str, str] | None = None, base_url: str = "https://huggingface.co") -> Path:
    """Tải mô hình ONNX về root/<repo>. Mạng đứt thì NỐI TIẾP phần đã tải (HTTP Range); kiểm SHA-256 tệp lớn.

    Tệp đã đủ byte mà sai mã băm (máy chủ trả 416 — không còn gì để tải tiếp) bị xoá và tải lại từ đầu.
    """
    import time as _t
    import urllib.error
    import urllib.request

    d = Path(root) / repo.replace("/", "__")
    for name, sha in (files or ONNX_MODELS[repo]).items():
        out = d / name
        out.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(attempts):
            if out.exists() and out.stat().st_size > 0 and (not sha or _sha256(out) == sha):
                break
            have = out.stat().st_size if out.exists() else 0
            req = urllib.request.Request(f"{base_url}/{repo}/resolve/main/{name}",
                                         headers={"Range": f"bytes={have}-"} if have else {})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    mode = "ab" if have and r.status == 206 else "wb"   # 200 = máy chủ gửi lại từ đầu
                    with open(out, mode) as f:
                        while chunk := r.read(1 << 20):
                            f.write(chunk)
            except urllib.error.HTTPError as e:
                if e.code == 416:                                    # đã đủ byte nhưng sai mã băm → hỏng
                    out.unlink(missing_ok=True)
                else:
                    print(f"  {name}: HTTP {e.code} — thử lại", flush=True)
                    _t.sleep(3)
            except OSError as e:                                     # đứt mạng, hết thời gian chờ…
                print(f"  {name}: {e} — thử lại", flush=True)
                _t.sleep(3)
        else:
            raise RuntimeError(f"Không tải được {repo}/{name}")
        print(f"  OK {repo}/{name}", flush=True)
    return d


def cache_path(cache_dir: str | Path, model: str) -> Path:
    return Path(cache_dir) / f"{model.replace('/', '__')}.npz"


def load_dense(cache_dir: str | Path, model: str, article_ids: list[str]) -> np.ndarray | None:
    """Ma trận (n_bài, d) theo đúng thứ tự `article_ids`; None nếu chưa có cache hoặc cache thiếu bài."""
    p = cache_path(cache_dir, model)
    if not p.exists():
        return None
    z = np.load(p, allow_pickle=False)
    pos = {a: i for i, a in enumerate(z["ids"].tolist())}
    if any(a not in pos for a in article_ids):
        return None
    return z["emb"][[pos[a] for a in article_ids]].astype(np.float32)


def mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Trung bình vector các token THẬT (mask = 1), rồi chuẩn hoá L2 — như pooling "mean" của sentence-transformers."""
    m = mask[..., None].astype(np.float32)
    v = (hidden * m).sum(1) / np.maximum(m.sum(1), 1e-9)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


class OnnxEncoder:
    """Chạy mô hình ONNX (bản Xenova/… trên Hugging Face) bằng onnxruntime trên CPU."""

    def __init__(self, model_dir: str | Path, max_len: int = 128):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = Path(model_dir)
        onnx = next(p for p in (d / "onnx/model_quantized.onnx", d / "onnx/model.onnx") if p.exists())
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_truncation(max_len)
        self.tok.enable_padding()
        opts = ort.SessionOptions()
        self.sess = ort.InferenceSession(str(onnx), opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        out = []
        for s in range(0, len(texts), batch_size):
            enc = self.tok.encode_batch(texts[s:s + batch_size])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.sess.run(None, feed)[0]
            out.append(mean_pool(hidden, mask))
            if (s // batch_size) % 50 == 0:
                print(f"  {s + len(enc)}/{len(texts)}", flush=True)
        return np.vstack(out)


def main(argv: list[str] | None = None) -> None:
    from eventrank.weak_labels.corpus import load_corpus
    from eventrank.weak_labels.entities import EntityNormalizer, load_aliases

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--gold", default="data/lake/gold/gold_data.jsonl")
    ap.add_argument("--silver-glob", default="data/lake/silver/*/*.jsonl")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--cache-dir", default="data/weak_labels/cache")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-seq-length", type=int, default=128)
    args = ap.parse_args(argv)

    arts, _, _ = load_corpus(args.gold, args.silver_glob, EntityNormalizer(load_aliases()))
    texts = [a.head_text() for a in arts]
    t0 = time.time()
    local = Path(LOCAL_MODELS) / args.model.replace("/", "__")
    if args.model in ONNX_MODELS:
        local = download_model(args.model)
    if (local / "tokenizer.json").exists():
        print(f"Mô hình ONNX cục bộ: {local}")
        emb = OnnxEncoder(local, args.max_seq_length).encode(texts, args.batch_size)
    else:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(args.model, device="cpu")
        model.max_seq_length = args.max_seq_length
        emb = model.encode(texts, batch_size=args.batch_size, normalize_embeddings=True,
                           show_progress_bar=True, convert_to_numpy=True)
    out = cache_path(args.cache_dir, args.model)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, ids=np.array([a.article_id for a in arts]), emb=emb.astype(np.float16))
    print(f"{len(texts)} bài · {emb.shape[1]} chiều · {time.time() - t0:.0f}s → {out}")


if __name__ == "__main__":
    main()
