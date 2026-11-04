"""Client HTTP lịch sự cho crawler (`eventrank.ingest.fetch`). Không gọi mạng: httpx.MockTransport;
không ngủ thật: đồng hồ + sleep giả tiêm vào."""
from itertools import pairwise

import httpx
import pytest

from eventrank.ingest import fetch
from eventrank.ingest.fetch import PoliteClient

UA = "PBL-EventLake/0.1 (nghien cuu sinh vien; +mailto:nhom@example.com)"


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def make(routes, clock=None, **kw):
    """routes: {url: Response | callable(request)}; thiếu robots.txt → 404 = cho phép."""
    clock = clock or FakeClock()
    log: list[tuple[float, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        log.append((clock(), url))
        assert req.headers["user-agent"] == UA
        r = routes.get(url)
        if r is None:
            return httpx.Response(404)
        return r(req) if callable(r) else r

    c = PoliteClient(UA, transport=httpx.MockTransport(handler), clock=clock, sleep=clock.sleep,
                     **kw)
    return c, log, clock


def ok(text="ok", ctype="text/html; charset=utf-8"):
    return httpx.Response(200, text=text, headers={"content-type": ctype})


def test_thieu_user_agent_bao_loi(monkeypatch):
    monkeypatch.delenv("CRAWLER_USER_AGENT", raising=False)
    monkeypatch.setattr(fetch, "load_dotenv", lambda *a, **k: False)
    with pytest.raises(fetch.CrawlerConfigError, match="CRAWLER_USER_AGENT"):
        PoliteClient()


def test_khong_cho_gia_user_agent_trinh_duyet():
    with pytest.raises(fetch.CrawlerConfigError, match="trình duyệt"):
        PoliteClient("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120")


def test_gian_cach_toi_thieu_2_giay_moi_domain():
    c, log, _ = make({"https://a.vn/1": ok(), "https://a.vn/2": ok(), "https://b.vn/1": ok()})
    c.get("https://a.vn/1")
    c.get("https://b.vn/1")
    c.get("https://a.vn/2")
    times = {}
    for t, u in log:
        times.setdefault(httpx.URL(u).host, []).append(t)
    for host, ts in times.items():          # robots.txt cũng tính là một request
        assert all(b - a >= 2.0 for a, b in pairwise(ts)), (host, ts)
    # b.vn không phải chờ a.vn
    assert log[2][1] == "https://b.vn/robots.txt" and log[2][0] == log[1][0]


def test_crawl_delay_lon_hon_thi_theo_robots():
    robots = ok("User-agent: *\nCrawl-delay: 5\n", "text/plain")
    c, log, _ = make({"https://a.vn/robots.txt": robots, "https://a.vn/1": ok(),
                      "https://a.vn/2": ok()})
    c.get("https://a.vn/1")
    c.get("https://a.vn/2")
    ts = [t for t, _ in log]
    assert ts[2] - ts[1] >= 5.0


def test_robots_chan_thi_khong_tai():
    robots = ok("User-agent: PBL-EventLake\nDisallow: /private/\n", "text/plain")
    c, log, _ = make({"https://a.vn/robots.txt": robots, "https://a.vn/private/x": ok()})
    with pytest.raises(fetch.RobotsDisallowed):
        c.get("https://a.vn/private/x")
    assert [u for _, u in log] == ["https://a.vn/robots.txt"]


def test_robots_403_coi_nhu_cam_toan_bo():
    c, _, _ = make({"https://a.vn/robots.txt": httpx.Response(403), "https://a.vn/x": ok()})
    with pytest.raises(fetch.RobotsDisallowed):
        c.get("https://a.vn/x")


def test_robots_chi_tai_mot_lan_moi_domain():
    c, log, _ = make({"https://a.vn/1": ok(), "https://a.vn/2": ok()})
    c.get("https://a.vn/1")
    c.get("https://a.vn/2")
    assert [u for _, u in log].count("https://a.vn/robots.txt") == 1


def test_get_xml_nhan_html_thay_xml_thi_nem_loi():
    # Bẫy VnExpress: sitemap 302 về trang chủ (HTML) → phải là LỖI, không phải "sitemap rỗng".
    routes = {
        "https://vnexpress.net/sitemap/2026-09-01.xml":
            httpx.Response(302, headers={"location": "https://vnexpress.net/"}),
        "https://vnexpress.net/": ok("<!DOCTYPE html><html><body>Trang chủ</body></html>"),
    }
    c, _, _ = make(routes)
    with pytest.raises(fetch.NotXmlError, match="302"):
        c.get_xml("https://vnexpress.net/sitemap/2026-09-01.xml")


def test_get_xml_bo_bom_dau_file():
    body = "﻿<?xml version='1.0'?><urlset></urlset>".encode()
    c, _, _ = make({"https://dantri.com.vn/s.xml": httpx.Response(
        200, content=body, headers={"content-type": "text/xml"})})
    assert c.get_xml("https://dantri.com.vn/s.xml").startswith(b"<?xml")


def test_403_lien_tiep_thi_dung_domain():
    c, log, _ = make({"https://a.vn/1": httpx.Response(403), "https://a.vn/2": httpx.Response(403),
                      "https://a.vn/3": ok()}, block_after_403=2)
    with pytest.raises(fetch.Forbidden):
        c.get("https://a.vn/1")
    with pytest.raises(fetch.DomainBlocked):
        c.get("https://a.vn/2")
    n = len(log)
    with pytest.raises(fetch.DomainBlocked):     # đã dừng: không gửi thêm request nào
        c.get("https://a.vn/3")
    assert len(log) == n


def test_429_cho_theo_retry_after_roi_thu_lai():
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "30"}) if calls["n"] == 1 else ok()

    c, _, clock = make({"https://a.vn/1": flaky})
    assert c.get("https://a.vn/1").status_code == 200
    assert calls["n"] == 2
    assert max(clock.sleeps) >= 30


def test_5xx_het_luot_thu_thi_nem_loi():
    calls = {"n": 0}

    def down(req):
        calls["n"] += 1
        return httpx.Response(503)

    c, _, clock = make({"https://a.vn/1": down}, max_retries=2, backoff=5.0)
    with pytest.raises(fetch.FetchError, match="503"):
        c.get("https://a.vn/1")
    assert calls["n"] == 3
    assert sum(clock.sleeps) >= 5 + 10       # backoff tăng dần


def test_theo_chuyen_huong_tung_buoc_deu_gian_cach():
    routes = {"https://a.vn/cu": httpx.Response(301, headers={"location": "/moi"}),
              "https://a.vn/moi": ok("xong")}
    c, log, _ = make(routes)
    r = c.get("https://a.vn/cu")
    assert r.text == "xong" and str(r.url) == "https://a.vn/moi"
    ts = [t for t, u in log if u != "https://a.vn/robots.txt"]
    assert ts[1] - ts[0] >= 2.0
