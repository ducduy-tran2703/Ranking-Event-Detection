from eventrank.lake.reader import Filters


def test_nap_du_tat_ca_ban_ghi(store):
    assert store.count() == 5


def test_chuan_hoa_ten_nguon_ve_chu_thuong(store):
    raw = {r["source_raw"]: r["source"] for r in store.quality()["raw_source_values"]}
    assert raw["BAOCHINHPHU"] == "baochinhphu"
    assert set(store.meta()["sources"]) == {"vnexpress", "baochinhphu"}


def test_bo_qua_cot_la_khong_co_trong_schema(store):
    assert store.get_article("b1")["title"].startswith("Đoàn Thể thao")


def test_tach_gio_theo_mui_gio_viet_nam(store):
    # 00:30 ngày 16/9 giờ VN phải rơi vào ngày 16/9, không bị lùi về 15/9 theo UTC
    rows = store.timeline(Filters(source="baochinhphu"), "day")
    assert {r["bucket"] for r in rows} == {"2026-09-16"}


def test_phat_hien_cac_loi_chat_luong(store):
    by_src = {r["source"]: r for r in store.quality()["issues_per_source"]}
    assert by_src["vnexpress"]["missing_author"] == 1      # author rỗng -> NULL
    assert by_src["vnexpress"]["short_content"] == 1
    assert by_src["vnexpress"]["duplicate_url"] == 2       # a1 và a3 cùng URL
    assert by_src["baochinhphu"]["empty_content"] == 1
    assert by_src["baochinhphu"]["missing_author"] == 1


def test_loc_theo_loi_de_duyet_bai(store):
    res = store.list_articles(Filters(issue="duplicate_url"))
    assert res["total"] == 2
    assert {i["article_id"] for i in res["items"]} == {"a1", "a3"}


def test_loc_theo_tu_khoa_va_khoang_ngay(store):
    res = store.list_articles(Filters(q="asiad", date_from="2026-09-16", date_to="2026-09-16"))
    assert [i["article_id"] for i in res["items"]] == ["b1"]


def test_phan_trang_va_gioi_han_kich_thuoc(store):
    res = store.list_articles(Filters(), page=2, page_size=2, sort="oldest")
    assert res["total"] == 5 and len(res["items"]) == 2 and res["page"] == 2


def test_tu_choi_tham_so_khong_hop_le(store):
    import pytest
    with pytest.raises(ValueError):
        store.list_articles(Filters(issue="drop table"))
    with pytest.raises(ValueError):
        store.list_articles(Filters(), sort="1; DROP TABLE articles")
    with pytest.raises(ValueError):
        store.timeline(Filters(), "minute")


def test_khong_tim_thay_bai_tra_ve_none(store):
    assert store.get_article("khong-ton-tai") is None


def test_phat_hien_file_moi_hon_lan_nap_va_cap_nhat_thi_het(tmp_path):
    """Crawler ghi file SAU lần nạp → báo có dữ liệu mới; bấm cập nhật → hết báo."""
    import os
    import shutil
    import time

    from eventrank.common.config import LakeConfig
    from eventrank.lake.reader import SilverStore

    shutil.copytree("tests/fixtures/silver", tmp_path / "silver")
    s = SilverStore(LakeConfig(backend="local", bucket="", silver_glob="silver/*/*.jsonl",
                               local_root=str(tmp_path)))
    s.reload()
    assert s.freshness(max_age_s=0)["has_newer_data"] is False

    # Giả lập crawler ghi đè file 0,2 giây sau lần nạp
    target = next((tmp_path / "silver" / "vnexpress").glob("*.jsonl"))
    written_at = s.loaded_at.timestamp() + 0.2
    os.utime(target, (written_at, written_at))
    fresh = s.freshness(max_age_s=0)
    assert fresh["has_newer_data"] is True
    assert fresh["newer_files"] == ["silver/vnexpress/articles_silver.jsonl"]

    time.sleep(0.3)                  # người dùng bấm "Cập nhật dữ liệu" sau khi file đã được ghi
    s.reload()
    assert s.freshness(max_age_s=0)["has_newer_data"] is False


def test_liet_ke_file_dung_lai_ket_qua_trong_thoi_gian_cho_phep(store):
    first = store.list_files(max_age_s=60)
    assert store.list_files(max_age_s=60) is first          # không liệt kê lại
    assert store.list_files(max_age_s=0) is not first       # max_age_s=0: luôn liệt kê mới


def test_thong_ke_source_kem_ten_thu_muc_tren_kho(store):
    """Trang Chất lượng cần biết tên thư mục để phát hiện nguồn ghi lệch tên thư mục."""
    rows = {r["source_raw"]: r for r in store.quality()["raw_source_values"]}
    assert rows["BAOCHINHPHU"]["folder"] == "baochinhphu"   # thư mục đúng, chỉ sai chữ hoa
    assert rows["BAOCHINHPHU"]["source"] == "baochinhphu"
    assert rows["vnexpress"]["folder"] == "vnexpress"
