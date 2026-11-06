import unicodedata
import uuid

import pytest

from eventrank.rag.bm25 import BM25Index, analyze, create_index


def records():
    return [{"chunk_id": str(uuid.UUID(int=i)), "article_id": str(i) * 64,
             "text": text, "title": title, "source": source, "url": f"https://example.test/{i}",
             "published_at": f"2026-09-{day}T08:00:00+07:00", "start_char": 0,
             "end_char": len(text), "chunking_version": "sample"}
            for i, text, title, source, day in [
                (1, "Tiêu đề: Khôi phục điện\n\nNội dung:\nQuảng Ninh khôi phục điện sau bão.",
                 "Khôi phục điện", "vnexpress", "10"),
                (2, "Đội tuyển Việt Nam thi đấu bóng đá.", "Đội tuyển", "tuoitre", "11"),
                (3, "TP.HCM triển khai Nghị quyết số 57-NQ/TW về khoa học công nghệ.",
                 "Triển khai nghị quyết", "vnexpress", "12"),
            ]]


def test_analyzer_nfc_codes_va_template_khong_lam_mat_tu_trong_than():
    tokens = analyze(unicodedata.normalize("NFD", "TP.HCM áp dụng 57-NQ/TW tại Hà Nội"))
    assert {"tp.hcm", "tp", "hcm", "57-nq/tw", "57", "nq", "tw", "hà", "nội"} <= set(tokens)
    assert analyze("Tiêu đề: Tin\n\nSapo: Mới\n\nNội dung:\nNội dung nghị quyết") == [
        "tin", "mới", "nội", "dung", "nghị", "quyết"]


def test_index_tren_disk_query_tieng_viet_nfd_va_codes(tmp_path):
    path = tmp_path / "index"
    assert create_index(records(), path)["documents"] == 3
    index = BM25Index(path)
    assert index.search("Quảng Ninh khôi phục điện")[0]["chunk_id"] == records()[0]["chunk_id"]
    assert index.search(unicodedata.normalize("NFD", "Quảng Ninh"))[0]["article_id"] == "1" * 64
    assert BM25Index(path).search("57-NQ/TW")[0]["article_id"] == "3" * 64
    assert index.search("TP.HCM")[0]["article_id"] == "3" * 64
    assert index.search("zqxvkhongtontai") == []
    assert index.search("text:* OR source:tuoitre") == []
    assert index.search(" \n!!!") == []


def test_filters_nguon_va_ngay_viet_nam(tmp_path):
    path = tmp_path / "index"
    create_index(records(), path)
    index = BM25Index(path)
    assert index.search("điện", source="tuoitre") == []
    assert index.search("điện", source="VNEXPRESS", date_from="2026-09-10",
                        date_to="2026-09-10")[0]["source"] == "vnexpress"
    assert index.search("điện", date_from="2026-09-11") == []


def test_khong_ghi_de_index_da_co_va_khong_nhan_duplicate_chunk(tmp_path):
    path = tmp_path / "index"
    create_index(records(), path)
    with pytest.raises(ValueError):
        create_index(records(), path)
    with pytest.raises(ValueError, match="trùng"):
        create_index([records()[0], records()[0]], tmp_path / "duplicate")


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101},
                                    {"date_from": "bad"},
                                    {"date_from": "2026-10-01", "date_to": "2026-09-01"}])
def test_tham_so_sai_phai_bao_loi(tmp_path, kwargs):
    path = tmp_path / "index"
    create_index(records(), path)
    with pytest.raises(ValueError):
        BM25Index(path).search("điện", **kwargs)
