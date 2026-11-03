import numpy as np

from eventrank.embeddings import encode as en


def _fake(calls):
    def enc(xs):
        calls.append(list(xs))
        E = np.array([[len(x), 1.0] for x in xs], dtype=np.float32)
        return E / np.linalg.norm(E, axis=1, keepdims=True)
    return enc


def test_head_text_va_prep():
    assert en.head_text("Tiêu đề", "Sapo") == "Tiêu đề. Sapo"
    assert en.head_text("Tiêu đề", "") == "Tiêu đề"
    assert en.prep("Hà Nội", "query") == "query: Hà Nội"
    assert en.prep("Hà Nội", "raw") == "Hà Nội"


def test_encode_dung_dem_chi_encode_bai_moi(tmp_path):
    cache, calls = tmp_path / "emb.npz", []
    out = en.encode({"a": "x", "b": "yy"}, "m", "raw", cache=cache, chunk=1, encoder=_fake(calls), log=lambda s: None)
    assert set(out) == {"a", "b"} and len(calls) == 2                  # chunk=1 → ghi đệm sau từng bài
    out2 = en.encode({"a": "x", "c": "zzz"}, "m", "raw", cache=cache, encoder=_fake(calls), log=lambda s: None)
    assert calls[-1] == ["zzz"] and set(out2) == {"a", "c"}            # chỉ trả bài được hỏi
    assert np.allclose(out2["a"], out["a"])


def test_encode_bo_dem_khi_doi_mo_hinh_hoac_tien_xu_ly(tmp_path):
    cache, calls = tmp_path / "emb.npz", []
    en.encode({"a": "x"}, "m1", "raw", cache=cache, encoder=_fake(calls), log=lambda s: None)
    en.encode({"a": "x"}, "m2", "raw", cache=cache, encoder=_fake(calls), log=lambda s: None)
    en.encode({"a": "x"}, "m2", "query", cache=cache, encoder=_fake(calls), log=lambda s: None)
    assert calls == [["x"], ["x"], ["query: x"]]


def test_encode_cache_key_doc_lap_voi_duong_dan(tmp_path):
    """File đệm sinh ở máy khác (Kaggle) có đường dẫn mô hình khác nhưng cùng cache_key → vẫn dùng được."""
    cache, calls = tmp_path / "emb.npz", []
    en.encode({"a": "x"}, "/kaggle/model", "raw", cache=cache, cache_key="v1", encoder=_fake(calls), log=lambda s: None)
    en.encode({"a": "x"}, "/home/x/model", "raw", cache=cache, cache_key="v1", encoder=_fake(calls), log=lambda s: None)
    assert calls == [["x"]]
