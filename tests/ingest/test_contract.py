"""Hợp đồng Silver (docs/tong-hop.md mục 5.3) cho một bài: chuẩn hoá + kiểm tra + cờ chất lượng."""
import hashlib
import unicodedata
from datetime import UTC, datetime

from eventrank.ingest import contract
from eventrank.ingest.contract import Article, Rejected

NOW = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
SOURCES = {"tuoitre", "baochinhphu"}
URL = "https://tuoitre.vn/bai-viet-1.htm"


def raw(**kw):
    r = {
        "url": URL, "source": "tuoitre", "category": "Thời sự",
        "title": "Tiêu đề bài", "sapo": "Đoạn sapo.", "author": "Minh Thư",
        "published_at": "2026-09-16T07:07:00+07:00",
        "content_text": " ".join(["từ"] * 120),
    }
    r.update(kw)
    return r


def check(r, **kw):
    return contract.validate_article(r, known_sources=SOURCES, now=NOW, **kw)


def codes(res):
    assert isinstance(res, Rejected), res
    return {e.split(":")[0] for e in res.errors}


def test_bai_hop_le_tinh_article_id_tu_url():
    a = check(raw())
    assert isinstance(a, Article)
    assert a.article_id == hashlib.sha256(URL.encode()).hexdigest()
    assert a.quality_flags == ()
    assert a.published_at == datetime(2026, 9, 16, 0, 7, tzinfo=UTC)


def test_article_id_co_san_phai_khop_url():
    good = hashlib.sha256(URL.encode()).hexdigest()
    assert isinstance(check(raw(article_id=good)), Article)
    assert "article_id_mismatch" in codes(check(raw(article_id="a1")))


def test_url_phai_https():
    assert "url_not_https" in codes(check(raw(url="http://tuoitre.vn/x.htm")))
    assert "url_missing" in codes(check(raw(url="")))


def test_source_viet_thuong_va_phai_co_trong_bang_sources():
    a = check(raw(source=" BAOCHINHPHU ", url="https://baochinhphu.vn/b1.htm"))
    assert isinstance(a, Article) and a.source == "baochinhphu"
    assert "source_unknown" in codes(check(raw(source="dantri")))


def test_source_phai_trung_crawler_khai_bao():
    assert "source_mismatch" in codes(check(raw(), expected_source="baochinhphu"))


def test_published_at_bat_buoc_co_mui_gio():
    assert "published_at_missing" in codes(check(raw(published_at="")))
    assert "published_at_naive" in codes(check(raw(published_at="2026-09-16T07:07:00")))
    assert "published_at_invalid" in codes(check(raw(published_at="10.9")))
    a = check(raw(published_at=datetime(2026, 9, 16, 0, 7, tzinfo=UTC)))
    assert isinstance(a, Article)


def test_thieu_tieu_de_hoac_chuyen_muc_bi_loai():
    assert "title_missing" in codes(check(raw(title="   ")))
    assert "category_missing" in codes(check(raw(category=None)))


def test_gom_nhieu_loi_mot_lan():
    res = check(raw(url="http://x", title="", published_at=""))
    assert {"url_not_https", "title_missing", "published_at_missing"} <= codes(res)


def test_author_rong_thanh_none_va_gan_co():
    for v in ("", "   ", None):
        a = check(raw(author=v))
        assert a.author is None
        assert "missing_author" in a.quality_flags


def test_chuan_hoa_nfc_va_khoang_trang():
    nfd = unicodedata.normalize("NFD", "Hà Nội")
    a = check(raw(title=f"  {nfd}   mưa\tlớn \n",
                  content_text=f"Đoạn  1 {nfd}\r\n\r\n\r\nĐoạn 2  "))
    assert a.title == "Hà Nội mưa lớn"
    assert unicodedata.is_normalized("NFC", a.title)
    assert a.content_text == "Đoạn 1 Hà Nội\n\nĐoạn 2"


def test_co_chat_luong_theo_nguong_5_3():
    assert check(raw(sapo="")).quality_flags == ("missing_sapo",)
    assert "no_body" in check(raw(content_text="")).quality_flags
    assert "short_body" in check(raw(content_text="ngắn quá")).quality_flags
    assert "short_body" not in check(raw(content_text=" ".join(["từ"] * 80))).quality_flags
    future = check(raw(published_at="2026-09-20T01:30:00+00:00")).quality_flags
    assert "future_date" in future
    assert "future_date" not in check(raw(published_at="2026-09-20T00:30:00+00:00")).quality_flags


def test_content_hash_doi_khi_noi_dung_doi_khong_doi_khi_chi_khac_khoang_trang():
    a = check(raw())
    assert a.content_hash == check(raw(title=" Tiêu  đề bài ")).content_hash
    assert a.content_hash != check(raw(title="Tiêu đề khác")).content_hash
    assert len(a.content_hash) == 64


def test_khong_phai_dict_bi_loai():
    assert "not_an_object" in codes(check(["không", "phải", "dict"]))


def test_to_silver_dung_hop_dong():
    s = check(raw(author="")).to_silver()
    assert set(s) == set(contract.SILVER_FIELDS)
    assert s["author"] is None and s["published_at"] == "2026-09-16T07:07:00+07:00"
