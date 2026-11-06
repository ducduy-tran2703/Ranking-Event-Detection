import random
import unicodedata
from itertools import pairwise

import pytest

from eventrank.rag.chunking import make_chunks
from eventrank.rag.text import build_full_text, validate_entities


def test_canonical_template_giu_khoang_trang_va_chuan_nfc():
    raw = {"title": " Hà Nội ", "sapo": " Tin  mới. ", "content_text": " Đoạn một.\n\nĐoạn hai. "}
    assert build_full_text(raw) == "Tiêu đề: Hà Nội\n\nSapo: Tin  mới.\n\nNội dung:\nĐoạn một.\n\nĐoạn hai."
    assert build_full_text({"title": " Tin ", "sapo": None}) == "Tiêu đề: Tin"


def test_entity_valid_va_bo_cac_truong_ky_thuat():
    text = "Hà Nội có tin mới."
    e = {"text": "Hà Nội", "label": "LOC", "start_char": 0, "end_char": 6, "rule": "sample"}
    assert validate_entities(text, [e]) == [{k: v for k, v in e.items() if k != "rule"}]


@pytest.mark.parametrize("patch", [
    {"start_char": -1}, {"end_char": 99}, {"text": "Hà Nam"},
    {"label": "DATE"}, {"start_char": True},
])
def test_entity_sai_offset_hoac_nhan_phai_dung(patch):
    e = {"text": "Hà Nội", "label": "LOC", "start_char": 0, "end_char": 6, **patch}
    with pytest.raises(ValueError):
        validate_entities("Hà Nội", [e])


def test_chunk_lap_lai_uuid_on_dinh_cover_text_va_overlap():
    text = "\n\n".join(" ".join(f"từ{i}" for i in range(a, a + 15)) + "." for a in range(0, 90, 15))
    chunks = make_chunks("a" * 64, text, [], max_units=25, overlap_units=5)
    assert len(chunks) >= 4
    assert chunks == make_chunks("a" * 64, text, [], max_units=25, overlap_units=5)
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)
    covered = set()
    for c in chunks:
        assert c["text"] == text[c["start_char"]:c["end_char"]]
        covered.update(range(c["start_char"], c["end_char"]))
        assert len(c["text"].split()) <= 25
    assert all(i in covered for i, ch in enumerate(text) if not ch.isspace())
    assert any(a["end_char"] > b["start_char"] for a, b in pairwise(chunks))
    changed = make_chunks("a" * 64, text, [], max_units=24, overlap_units=5)
    assert chunks[0]["chunking_version"] != changed[0]["chunking_version"]


def test_khong_cat_entity_ke_ca_entity_dai_va_chong_lan():
    text = "mở " + " ".join(["Tên"] * 20) + " xong thêm nhiều từ khác nữa."
    entities = [{"text": text[3:82], "label": "ORG", "start_char": 3, "end_char": 82}]
    chunks = make_chunks("a" * 64, text, entities, max_units=8, overlap_units=2)
    assert chunks
    for c in chunks:
        for e in entities:
            assert not e["start_char"] < c["start_char"] < e["end_char"]
            assert not e["start_char"] < c["end_char"] < e["end_char"]


def test_text_ngan_rong_va_unicode():
    assert make_chunks("a" * 64, " \n", []) == []
    text = unicodedata.normalize("NFC", "Hà Nội có tin mới.")
    chunks = make_chunks("a" * 64, text, [])
    assert len(chunks) == 1 and chunks[0]["text"] == text


def test_cau_hinh_overlap_khong_duoc_gay_lap_vo_han():
    with pytest.raises(ValueError):
        make_chunks("a" * 64, "tin", [], max_units=10, overlap_units=10)


def test_span_sat_dau_cau_va_overlapping_khong_mat_ky_tu():
    rng = random.Random(42)
    text = " ".join(f"từ{i}," for i in range(35))
    for _ in range(100):
        spans = sorted((rng.randrange(len(text) - 2), rng.randrange(1, len(text)))
                       for _ in range(3))
        entities = [{"start_char": lo, "end_char": hi, "text": text[lo:hi], "label": "ORG"}
                    for lo, hi in spans if lo < hi]
        chunks = make_chunks("a" * 64, text, entities, max_units=8, overlap_units=2)
        covered = set()
        for c in chunks:
            covered.update(range(c["start_char"], c["end_char"]))
            for e in entities:
                assert not e["start_char"] < c["start_char"] < e["end_char"]
                assert not e["start_char"] < c["end_char"] < e["end_char"]
        assert all(i in covered for i, ch in enumerate(text) if not ch.isspace())
