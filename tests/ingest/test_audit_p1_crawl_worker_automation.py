"""Kiểm tra hệ thống (P1-crawl-worker): dịch vụ cào 8 báo (automation/, crawler/). Offline, không gọi báo thật.

Test `xfail(strict=True)` tái hiện lỗi đã xác nhận (AUDIT-P1-crawl-worker-<số>, xem báo cáo); test thường là hàng rào
cho hành vi đang đúng.
"""
import io
import json
import threading
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from automation import pipeline as automation_pipeline
from automation.config import SOURCES, Settings
from automation.discovery import DiscoveryIncomplete, canonical_url, discover
from automation.http import SourceBlocked, SourceClient
from automation.pipeline import Pipeline
from automation.scheduler import VN_TZ
from automation.state import SourceState
from crawler.common_utils import compute_article_id

BODY = "Nội dung bài báo phục vụ kiểm thử đủ dài để qua bước làm sạch. " * 6
QDND_URL = "https://www.qdnd.vn/kinh-te/bai-viet-audit-1"
QDND_HTML = f'''<div class="article-detail"><h1 class="post-title">Tiêu đề bài báo kiểm thử</h1>
<div class="post-summary">Giới thiệu.</div>
<span class="post-subinfo">Thứ hai, 23/11/2026 - 08:00</span>
<div itemprop="articleBody"><p>{BODY}</p><p>Đoạn thứ hai của bài, tách khỏi đoạn đầu.</p></div></div>'''


@pytest.fixture(autouse=True)
def _ua(monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (audit)")


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, scheduler_enabled=False, max_article_age_days=0)


class _Client:
    """Thay SourceClient: trả HTML cố định, đếm request."""
    calls = 0

    def __init__(self, *args):
        pass

    def check(self):
        pass

    def get(self, url):
        type(self).calls += 1
        return Mock(text=QDND_HTML)

    def close(self):
        pass


def _exported_ids(root: Path, source: str) -> set[str]:
    out = set()
    for path in root.glob(f"jobs/*/clean_silver/{source}.jsonl"):
        out |= {json.loads(line)["article_id"] for line in path.read_text().splitlines() if line.strip()}
    return out


class _Killed(BaseException):
    """Tiến trình bị giết (SIGKILL, hết RAM, tắt máy) đúng lúc ghi file xuất của job."""


# --------------------------------------------------------------------------- AUDIT-1: mất bài khi job chết
def test_bai_sach_cua_job_bi_giet_van_duoc_xuat_o_job_sau(settings):
    pipe = Pipeline(settings, threading.Event())
    real_write_text = automation_pipeline.write_text

    def killed_at_export(path, value):
        raise _Killed()

    with patch("automation.pipeline.discover", return_value=iter([(QDND_URL, "Kinh Tế")])), \
         patch("automation.pipeline.SourceClient", _Client), \
         patch("automation.pipeline.write_text", killed_at_export), pytest.raises(_Killed):
        pipe.run_source("qdnd", "job-chet", lambda _s: None)
    key = compute_article_id(QDND_URL)
    assert SourceState(settings.data_dir, "qdnd").articles[key]["status"] == "clean"
    assert pipe.article_path("clean_silver", "qdnd", key).exists()

    # Tiến trình khởi động lại, job kế tiếp chạy bình thường (lần này discovery chỉ thấy lại URL cũ).
    assert automation_pipeline.write_text is real_write_text
    with patch("automation.pipeline.discover", return_value=iter([(QDND_URL, "Kinh Tế")])), \
         patch("automation.pipeline.SourceClient", _Client):
        pipe.run_source("qdnd", "job-sau", lambda _s: None)
    # db_sink chỉ nạp các file jobs/*/clean_silver/<source>.jsonl → bài phải nằm trong ít nhất một file xuất.
    assert key in _exported_ids(settings.data_dir, "qdnd")


# --------------------------------------------------------------------------- AUDIT-2: mất xuống dòng thân bài
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="AUDIT-P1-crawl-worker-2: process_data.clean_record.norm gộp cả '\\n' → "
                                       "content_text của bài cào trực tiếp mất ranh giới đoạn (hợp đồng 5.3 giữ đoạn)")
def test_clean_silver_giu_xuong_dong_giua_cac_doan(settings):
    pipe = Pipeline(settings, threading.Event())
    key = compute_article_id(QDND_URL)
    client = Mock()
    client.get.return_value = Mock(text=QDND_HTML)
    assert pipe.process_article("qdnd", key, {"url": QDND_URL, "category": "Kinh Tế"}, client) == ("clean", None)
    silver = json.loads(pipe.article_path("silver", "qdnd", key).read_text())
    assert "\n" in silver["content_text"]                      # Silver còn đoạn
    clean = json.loads(pipe.article_path("clean_silver", "qdnd", key).read_text())
    assert "\n" in clean["content_text"]                       # clean_silver (thứ vào DB) phải còn


# --------------------------------------------------------------------------- AUDIT-3: link ngoài báo trong listing
def test_listing_baochinhphu_bo_link_ngoai_bao_va_khong_https(settings):
    base = "https://baochinhphu.vn"
    html = ('<div class="list__listing">'
            '<a class="box-stream-link-title" href="/bai-that-102261123080000000.htm">x</a>'
            '<a class="box-stream-link-title" href="https://media.chinhphu.vn/video-1.htm">x</a>'
            '<a class="box-stream-link-title" href="http://baochinhphu.vn/bai-http-102261123090000000.htm">x</a>'
            '</div>')
    client = Mock()
    client.get.side_effect = [Mock(text=html), Mock(text="")]
    with patch("automation.discovery.CP_CATEGORIES", [{"category_url": base, "zone_id": 1, "category_label": "t"}]):
        found = [u for u, _ in discover("baochinhphu", client, set(), datetime.now(VN_TZ), settings)]
    assert all(u.startswith(base + "/") for u in found), found


def test_bai_that_bai_het_luot_lam_moi_job_sau_partial(settings):
    """Hành vi hiện tại (ghi lại cho pha sửa): một bài 'failed' hết lượt từ job CŨ làm mọi job sau 'partial'."""
    state = SourceState(settings.data_dir, "qdnd")
    key = state.add("https://media.chinhphu.vn/x.htm", "Kinh Tế")
    state.articles[key].update(status="failed", attempts=settings.max_article_attempts)
    state.save()
    with patch("automation.pipeline.discover", return_value=iter([])), \
         patch("automation.pipeline.SourceClient", _Client):
        stats = Pipeline(settings, threading.Event()).run_source("qdnd", "job-moi", lambda _s: None)
    assert (stats["status"], stats["exhausted"], stats["processed"]) == ("partial", 1, 0)


# --------------------------------------------------------------------------- AUDIT-4: chuẩn hoá URL không đồng nhất
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="AUDIT-P1-crawl-worker-4: canonical_url (4 báo mới) giữ http:// và www., "
                                       "4 báo cũ ép https + bỏ www → cùng bài có thể ra hai article_id")
@pytest.mark.parametrize("variant", ["http://nhandan.vn/chinhtri/bai-1.html",
                                     "https://www.nhandan.vn/chinhtri/bai-1.html"])
def test_canonical_url_gop_bien_the_cua_cung_mot_bai(variant):
    assert compute_article_id(canonical_url(variant)) == compute_article_id(
        canonical_url("https://nhandan.vn/chinhtri/bai-1.html"))


def test_canonical_url_bo_query_fragment_va_ha_chu_host():
    assert canonical_url(" https://NhanDan.vn/a.html?utm_source=x#top ") == "https://nhandan.vn/a.html"


@pytest.mark.parametrize("module, href", [
    ("tuoitre", "http://www.tuoitre.vn/bai-viet-100261123080000000.htm?ref=home#c"),
    ("thanhnien", "http://www.thanhnien.vn/bai-viet-185261123080000000.htm?x=1"),
    ("vnexpress", "http://www.vnexpress.net/bai-viet-4900000.html#box"),
    ("vietnamnet", "http://www.vietnamnet.vn/bai-viet-2400000.html?utm=1"),
])
def test_bon_bao_cu_ep_https_khong_www(module, href):
    from importlib import import_module
    mod = import_module(f"crawler.harvester_{module}")
    url = mod.normalize_article_url(href)
    assert url is not None and url.startswith("https://") and "www." not in url and "?" not in url and "#" not in url


# --------------------------------------------------------------------------- AUDIT-5: sitemap bị chuyển hướng
def _session_redirect_then_html():
    redirect = requests.Response()
    redirect.status_code = 302
    redirect.headers["Location"] = "/"
    redirect.raw = io.BytesIO(b"")
    home = requests.Response()
    home.status_code = 200
    home._content = b"<!doctype html><html><body>Trang chu</body></html>"
    session = Mock()
    session.get.side_effect = [redirect, home]
    return session


@pytest.mark.xfail(strict=True, raises=pytest.fail.Exception, reason="AUDIT-P1-crawl-worker-5: dantri/qdnd (báo sitemap) tự theo 302 thay vì dừng "
                                       "và báo (AGENTS.md mục 3); robots.txt không được kiểm lại ở đích chuyển hướng")
@pytest.mark.parametrize("source, url", [("dantri", "https://dantri.com.vn/sitemaps/articles.xml"),
                                         ("qdnd", "https://www.qdnd.vn/sitemaps/pid/feed-0.xml")])
def test_sitemap_bi_302_thi_dung_nguon(settings, source, url):
    s = Settings(data_dir=settings.data_dir, delays=dict.fromkeys(SOURCES, 0))
    client = SourceClient(source, s, threading.Event())
    with patch.object(client, "_session", return_value=_session_redirect_then_html()), \
         patch.object(client, "_check_robots"), pytest.raises(SourceBlocked):
        client.get(url)


def test_bao_cu_bi_302_thi_dung_nguon(settings):
    s = Settings(data_dir=settings.data_dir, delays=dict.fromkeys(SOURCES, 0))
    client = SourceClient("vnexpress", s, threading.Event())
    with patch.object(client, "_session", return_value=_session_redirect_then_html()), \
         patch.object(client, "_check_robots"), pytest.raises(SourceBlocked):
        client.get("https://vnexpress.net/the-thao")
    assert client.blocked.is_set()


@pytest.mark.parametrize("payload", [b"<!doctype html><html><body>captcha</body></html>",
                                     b"<html><head></head><body></body></html>"])
def test_sitemap_tra_html_la_loi_khong_phai_rong(settings, payload):
    client = Mock()
    client.get.return_value = Mock(content=payload)
    with pytest.raises(Exception) as err:
        list(discover("dantri", client, set(), datetime.now(VN_TZ), settings))
    assert not isinstance(err.value, StopIteration)
    assert isinstance(err.value, (DiscoveryIncomplete, SyntaxError))   # ParseError là SyntaxError


# --------------------------------------------------------------------------- giãn cách request
def test_gian_cach_tinh_ca_buoc_chuyen_huong_va_lan_thu_lai(settings):
    """2 s/request/domain: mọi lần BẮT ĐẦU request (cả bước 302 của báo mới, cả lần thử lại 5xx) đều cách nhau."""
    s = Settings(data_dir=settings.data_dir, delays={**dict.fromkeys(SOURCES, 0), "nhandan": 0.05})
    client = SourceClient("nhandan", s, threading.Event())
    starts = []
    redirect = requests.Response()
    redirect.status_code = 302
    redirect.headers["Location"] = "/b.html"
    redirect.raw = io.BytesIO(b"")
    err = requests.Response()
    err.status_code = 503
    ok = requests.Response()
    ok.status_code = 200
    seq = iter([redirect, err, redirect, ok])

    def get(*_a, **_k):
        starts.append(__import__("time").monotonic())
        return next(seq)

    session = Mock()
    session.get.side_effect = get
    with patch.object(client, "_session", return_value=session), patch.object(client, "_check_robots"), \
         patch.object(client, "_wait", wraps=client._wait):
        client.get("https://nhandan.vn/a.html")
    assert len(starts) == 4
    assert all(b - a >= 0.045 for a, b in pairwise(starts)), starts


def test_bao_cu_luon_gian_cach_toi_thieu_2_giay(settings):
    s = Settings(data_dir=settings.data_dir, delays=dict.fromkeys(SOURCES, 0))
    assert all(SourceClient(src, s, threading.Event()).delay >= 2.0
               for src in ("tuoitre", "thanhnien", "vietnamnet", "vnexpress"))
    # 4 báo mới không có sàn 2 s trong SourceClient: chỉ Settings.delays mặc định giữ 2 s (dantri 4 s).
    assert SourceClient("dantri", s, threading.Event()).delay == 0
    assert all(v >= 2.0 for v in Settings(data_dir=settings.data_dir).delays.values())


# --------------------------------------------------------------------------- AUDIT-6: tải lại bài cũ hàng loạt
def test_timeline_tuoitre_dung_khi_gap_bai_cu_hon_since(settings):
    s = Settings(data_dir=settings.data_dir, max_article_age_days=0, max_listing_pages=100)
    since = datetime(2026, 11, 23, 8, 0, tzinfo=VN_TZ)
    pages = {}

    def page_html(page):
        # Trang 1 có bài mới; từ trang 2 toàn bài tháng 8 (chưa từng thấy) — đúng kiểu dữ liệu thật 10/11.
        stamp = "261123090000" if page == 1 else f"2608{(page % 28) + 1:02d}080000"
        return "".join(f'<div class="box-category-item"><a class="box-category-link-title" '
                       f'href="/bai-{page}-{i}-100{stamp}{i:03d}.htm">x</a></div>' for i in range(20))

    def get(url):
        page = int(url.rsplit("trang-", 1)[1].split(".")[0])
        pages[page] = pages.get(page, 0) + 1
        return Mock(text=page_html(page))

    client = Mock()
    client.get.side_effect = get
    known = {"https://tuoitre.vn/da-biet-100261122080000000.htm"}
    with patch("crawler.harvester_tuoitre.TARGET_CATEGORIES", {"Kinh Tế": "11"}):
        try:
            list(discover("tuoitre", client, known, since, s))
        except DiscoveryIncomplete:
            pass
    assert max(pages) <= 3, f"quét {max(pages)} trang dù từ trang 2 toàn bài cũ hơn since"


def test_bai_cu_hon_han_bi_loai_sau_khi_da_tai(settings):
    """Hành vi hiện tại: lọc tuổi CHỈ chạy sau khi đã tải trang (mỗi bài cũ tốn 1 request ≥ 2 s)."""
    s = Settings(data_dir=settings.data_dir, max_article_age_days=7)
    pipe = Pipeline(s, threading.Event())
    old = QDND_HTML.replace("23/11/2026", (datetime.now(VN_TZ) - timedelta(days=60)).strftime("%d/%m/%Y"))
    client = Mock()
    client.get.return_value = Mock(text=old)
    key = compute_article_id(QDND_URL)
    assert pipe.process_article("qdnd", key, {"url": QDND_URL, "category": "Kinh Tế"}, client) == (
        "rejected", "older_than_max_age")
    assert client.get.call_count == 1


# --------------------------------------------------------------------------- 4 báo mới: ngày đăng
def _bronze(source, html, url):
    from importlib import import_module
    return import_module(f"crawler.silver_transformer_{source}").transform_record(
        {"url": url, "raw_html": html, "category": "Kinh Tế"})


def test_nhandan_ngay_khong_mui_gio_lot_qua_silver_roi_bi_db_loai():
    """nhandan giữ nguyên chuỗi meta: thiếu offset vẫn qua Silver + clean_record? → contract DB loại published_at_naive."""
    from eventrank.ingest.contract import Rejected, validate_article
    from process_data.clean_record import clean_record
    html = ('<div class="article"><h1 class="article__title cms-title">Tiêu đề bài kiểm thử</h1>'
            '<div class="article__sapo cms-desc">Sapo.</div>'
            '<meta class="cms-date" itemprop="datePublished" content="2026-11-23T08:00:00">'
            f'<div class="article__body zce-content-body cms-body"><p>{BODY}</p></div></div>')
    silver = _bronze("nhandan", html, "https://nhandan.vn/bai-1.html")
    assert silver is not None and silver["published_at"] == "2026-11-23T08:00:00"
    cleaned, reason = clean_record(silver)
    assert cleaned is None and reason == "bad_published_at"          # bị chặn ở clean_record, không vào DB
    res = validate_article({**silver, "source": "nhandan"}, known_sources={"nhandan"},
                           now=datetime(2026, 11, 23, tzinfo=VN_TZ))
    assert isinstance(res, Rejected) and "published_at_naive" in res.codes


CP_HEAD = ('<article class="detail-mcontent"><h1 class="detail-title">Tiêu đề bài kiểm thử</h1>'
           '<h2 class="detail-sapo">(Chinhphu.vn) - Sapo.</h2>')
CP_ONE_NODE = CP_HEAD + '<div data-role="publishdate">23/11/2026 08:00</div></article>'
CP_OK = CP_HEAD + '<div data-role="publishdate">23/11/2026<span class="icon"></span>08:00</div></article>'
DT_TIME = ('<time class="dt-flex dt-items-center dt-font-Inter dt-text-13px dt-leading-5 dt-text-common-sapo" '
           'datetime="{}"></time>')
DT_EMAG_ISO = ('<article class="e-magazine bg-wrap d-magazine"><h1 class="e-magazine__title">Tiêu đề</h1>'
               '<h2 class="e-magazine__sapo">(Dân trí) - Sapo.</h2>'
               + DT_TIME.format("2026-11-23T08:00:00+07:00") + "</article>")
DT_OK = ('<div class="dt-flex dt-flex-col dt-space-y-6"><h1 class="dt-font-inter dt-font-semibold '
         'dt-text-black dt-text-4xl dt-leading-12 -dt-mb-3">Tiêu đề</h1><h2 class="dt-font-arial '
         'dt-font-normal dt-text-lg dt-leading-160 dt-text-black-mine">(Dân trí) - Sapo.</h2>'
         + DT_TIME.format("2026-11-23 08:00") + "</div>")


@pytest.mark.parametrize("source, html, expected", [
    ("qdnd", QDND_HTML.replace("23/11/2026 - 08:00", "3/11/2026 - 8:00"), None),
    ("baochinhphu", CP_ONE_NODE, None),
    ("dantri", DT_EMAG_ISO, None),
])
def test_dinh_dang_ngay_la_bi_bo_qua_khong_doan(source, html, expected):
    """Ghi lại: định dạng ngày khác mẫu đã khảo sát → transformer trả None (bài 'rejected'), không đoán sai giờ."""
    assert _bronze(source, html, "https://x.vn/bai") is expected


@pytest.mark.parametrize("source, html, iso", [
    ("qdnd", QDND_HTML, "2026-11-23T08:00:00+07:00"),
    ("baochinhphu", CP_OK, "2026-11-23T08:00:00+07:00"),
    ("dantri", DT_OK, "2026-11-23T08:00:00+07:00"),
])
def test_ngay_dang_4_bao_moi_luon_gio_viet_nam(source, html, iso):
    silver = _bronze(source, html, "https://x.vn/bai")
    assert silver is not None and silver["published_at"] == iso


# --------------------------------------------------------------------------- PATCH /crawl/schedule giá trị lạ
@pytest.mark.parametrize("body", [{"interval_minutes": 7}, {"interval_minutes": "15"}, {"interval_minutes": None},
                                  {"enabled": None}, {"sources": []}, {"sources": ["QDND"]}, {"sources": None},
                                  {"last_slot": "2030-01-01T00:00:00+07:00"}, {"interval_minutes": 0}])
def test_patch_schedule_gia_tri_la_bi_422_va_khong_ghi_file(settings, body):
    from fastapi.testclient import TestClient

    from api.main import create_app
    from automation.job_manager import JobManager

    class Quiet(JobManager):
        def _loop(self):
            self.stop.wait()

    with TestClient(create_app(settings, Quiet)) as client:
        before = client.get("/crawl/schedule").json()
        assert client.patch("/crawl/schedule", json=body).status_code == 422
        after = client.get("/crawl/schedule").json()
    assert {k: before[k] for k in ("enabled", "interval_minutes", "sources", "last_slot")} == \
           {k: after[k] for k in ("enabled", "interval_minutes", "sources", "last_slot")}
    assert not (settings.data_dir / "state" / "schedule.json").exists()


def test_hai_job_cung_luc_chi_mot_duoc_nhan(settings):
    from concurrent.futures import ThreadPoolExecutor

    from automation.job_manager import JobConflict, JobManager

    release = threading.Event()

    class Holding:
        def __init__(self, *_a):
            pass

        def run(self, job, report, retry_failed):
            release.wait(5)
            return {s: {"status": "completed"} for s in job["sources"]}

    class Quiet(JobManager):
        def _loop(self):
            self.stop.wait()

    manager = Quiet(settings, Holding)
    manager.start()
    try:
        def submit(_):
            try:
                return manager.submit(["qdnd"])["id"]
            except JobConflict:
                return None
        with ThreadPoolExecutor(8) as pool:
            ids = [i for i in pool.map(submit, range(8)) if i]
        assert len(ids) == 1
    finally:
        release.set()
        manager.close()


# --------------------------------------------------------------------------- AUDIT-12: thiếu sapo bị loại thay vì gắn cờ
ND_NO_SAPO = ('<div class="article"><h1 class="article__title cms-title">Tiêu đề bài kiểm thử thiếu sapo</h1>'
              '<meta class="cms-date" itemprop="datePublished" content="2026-11-23T08:00:00+07:00">'
              f'<div class="article__body zce-content-body cms-body"><p>{BODY}</p></div></div>')
CP_NO_SAPO = CP_OK.replace('<h2 class="detail-sapo">(Chinhphu.vn) - Sapo.</h2>', "")
QD_NO_SAPO = QDND_HTML.replace('<div class="post-summary">Giới thiệu.</div>', "")
DT_NO_SAPO = DT_OK.replace('<h2 class="dt-font-arial dt-font-normal dt-text-lg dt-leading-160 dt-text-black-mine">'
                           '(Dân trí) - Sapo.</h2>', "")


@pytest.mark.parametrize("source, html", [("nhandan", ND_NO_SAPO), ("baochinhphu", CP_NO_SAPO),
                                          ("qdnd", QD_NO_SAPO), ("dantri", DT_NO_SAPO)])
def test_thieu_sapo_van_giu_bai_de_gan_co(source, html):
    silver = _bronze(source, html, "https://x.vn/bai")
    assert silver is not None and silver["sapo"] in ("", None)


# --------------------------------------------------------------------------- hàng rào cho bản sửa (pha 2, F-crawl)
def _run_qdnd(pipe, job_id, urls=(QDND_URL,)):
    with patch("automation.pipeline.discover", return_value=iter([(u, "Kinh Tế") for u in urls])), \
         patch("automation.pipeline.SourceClient", _Client):
        return pipe.run_source("qdnd", job_id, lambda _s: None)


def _ids_in(root: Path, job_id: str, source: str) -> list[str]:
    path = root / "jobs" / job_id / "clean_silver" / f"{source}.jsonl"
    return [json.loads(line)["article_id"] for line in path.read_text().splitlines() if line.strip()]


def test_bai_da_xuat_khong_bi_xuat_lai_o_job_sau(settings):
    """AUDIT-1: xuất bù chỉ áp cho bài CHƯA xuất; job bình thường xong thì job sau không xuất lại."""
    pipe = Pipeline(settings, threading.Event())
    _run_qdnd(pipe, "job-1")
    key = compute_article_id(QDND_URL)
    assert _ids_in(settings.data_dir, "job-1", "qdnd") == [key]
    _run_qdnd(pipe, "job-2")
    assert _ids_in(settings.data_dir, "job-2", "qdnd") == []


def test_bai_sach_tu_truoc_khi_co_co_xuat_khong_tu_xuat_bu(settings):
    """AUDIT-1: state cũ (trước bản sửa) không có mốc theo dõi → không tự xuất bù hàng loạt vào DB; việc đó để người dùng quyết."""
    state = SourceState(settings.data_dir, "qdnd")
    key = state.add(QDND_URL, "Kinh Tế")
    state.articles[key].update(status="clean")
    state.save()
    pipe = Pipeline(settings, threading.Event())
    pipe.article_path("clean_silver", "qdnd", key).parent.mkdir(parents=True)
    pipe.article_path("clean_silver", "qdnd", key).write_text(json.dumps({"article_id": key}))
    _run_qdnd(pipe, "job-dau-tien-sau-sua", urls=())
    assert _ids_in(settings.data_dir, "job-dau-tien-sau-sua", "qdnd") == []


def _timeline_pages(stamp_of_page, prefix="100", pattern="/bai-{page}-{i}-{prefix}{stamp}{i:03d}.htm"):
    def page_html(page):
        stamp = stamp_of_page(page)
        return "".join(f'<div class="box-category-item"><a class="box-category-link-title" '
                       f'href="{pattern.format(page=page, i=i, prefix=prefix, stamp=stamp)}">x</a></div>'
                       for i in range(20))
    return page_html


@pytest.mark.parametrize("source, zone_patch, prefix, page_of", [
    ("tuoitre", "crawler.harvester_tuoitre.TARGET_CATEGORIES", "100", lambda url: int(url.rsplit("trang-", 1)[1].split(".")[0])),
    ("thanhnien", "crawler.harvester_thanhnien.TARGET_CATEGORIES", "185", lambda url: int(url.rsplit("/", 1)[1].split(".")[0])),
])
def test_timeline_bo_url_cu_va_giu_url_moi(settings, source, zone_patch, prefix, page_of):
    """AUDIT-6: URL có ngày trong ID cũ hơn since − biên → không đưa vào state (không tải); URL mới vẫn giữ."""
    s = Settings(data_dir=settings.data_dir, max_article_age_days=0, max_listing_pages=100)
    since = datetime(2026, 11, 23, 8, 0, tzinfo=VN_TZ)
    seen = []
    html = _timeline_pages(lambda page: "261123090000" if page == 1 else "260801080000", prefix=prefix)

    def get(url):
        seen.append(page_of(url))
        return Mock(text=html(page_of(url)))

    client = Mock()
    client.get.side_effect = get
    with patch(zone_patch, {"Kinh Tế": "11"}):
        found = [u for u, _ in discover(source, client, {"https://x.vn/da-biet"}, since, s)]
    assert seen == [1, 2]                                    # trang 2 toàn bài cũ → dừng, không báo "Reached 100 pages"
    assert len(found) == 20 and all(f"{prefix}261123090000" in u for u in found)


def test_timeline_giu_url_trong_bien_va_url_khong_co_ngay(settings):
    """AUDIT-6: ID tạo lúc soạn bản nháp có thể sớm hơn giờ đăng vài ngày → chỉ bỏ khi cũ hơn since − 7 ngày; ID không đọc được thì giữ."""
    s = Settings(data_dir=settings.data_dir, max_article_age_days=0, max_listing_pages=100)
    since = datetime(2026, 11, 23, 8, 0, tzinfo=VN_TZ)
    page1 = ('<div class="box-category-item"><a class="box-category-link-title" href="/a-100261118080000001.htm">x</a></div>'
             '<div class="box-category-item"><a class="box-category-link-title" href="/b-20260323114749507.htm">x</a></div>'
             '<div class="box-category-item"><a class="box-category-link-title" href="/c-100261199080000001.htm">x</a></div>'
             '<div class="box-category-item"><a class="box-category-link-title" href="/d-100261110080000001.htm">x</a></div>')
    client = Mock()
    client.get.side_effect = [Mock(text=page1), Mock(text="")]
    with patch("crawler.harvester_tuoitre.TARGET_CATEGORIES", {"Kinh Tế": "11"}):
        found = [u for u, _ in discover("tuoitre", client, {"https://x.vn/da-biet"}, since, s)]
    # a: 5 ngày trước since (trong biên) · b: không có tiền tố 100 · c: ngày không hợp lệ → giữ; d: 13 ngày trước → bỏ
    assert [u.rsplit("/", 1)[1][0] for u in found] == ["a", "b", "c"]


def test_listing_nhandan_bo_link_ngoai_bao_va_khong_https(settings):
    """AUDIT-3 (nhandan): trang 1 SSR và trang API đều chỉ giữ https://nhandan.vn/…"""
    api = Mock()
    api.json.return_value = {"data": {"load_more": False, "contents": [
        {"url": "/bai-api-post4.html"}, {"url": "https://ngoai.vn/post5.html"}, {"url": "http://nhandan.vn/post6.html"}]}}
    client = Mock()
    client.get.side_effect = [Mock(text="<html></html>"), api]
    with patch("automation.discovery.ND_CATEGORIES", [{"category_url": "https://nhandan.vn/x", "zone_id": 1,
                                                       "category_label": "t"}]), \
         patch("automation.discovery.nd._extract_ssr_urls",
               return_value=["https://nhandan.vn/bai-that-post1.html", "https://media.nhandan.vn/x-post2.html",
                             "http://nhandan.vn/bai-http-post3.html"]):
        found = [u for u, _ in discover("nhandan", client, set(), datetime.now(VN_TZ), settings)]
    assert found == ["https://nhandan.vn/bai-that-post1.html", "https://nhandan.vn/bai-api-post4.html"], found


@pytest.mark.parametrize("source, html", [("nhandan", ND_NO_SAPO), ("qdnd", QD_NO_SAPO)])
def test_thieu_sapo_qua_clean_record_va_contract_gan_co(source, html):
    """AUDIT-12: sapo "" đi qua clean_record (None mới bị loại 'missing:sapo') và contract gắn cờ missing_sapo."""
    from eventrank.ingest.contract import validate_article
    from process_data.clean_record import clean_record
    silver = _bronze(source, html, f"https://{source}.vn/bai-1.html")
    cleaned, reason = clean_record(silver)
    assert cleaned is not None, reason
    res = validate_article({**cleaned, "source": source}, known_sources={source},
                           now=datetime(2026, 11, 24, tzinfo=VN_TZ))
    assert "missing_sapo" in res.quality_flags
