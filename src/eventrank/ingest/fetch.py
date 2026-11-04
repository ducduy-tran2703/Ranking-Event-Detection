"""Client HTTP "lịch sự" cho người viết crawler — mọi request tới báo PHẢI đi qua đây.

Gói sẵn các quy tắc AGENTS.md mục 3 để từng crawler không phải tự nhớ:
- Giãn cách ≥ `min_delay` (mặc định 2 s) giữa hai request tới CÙNG một domain, tính từ lúc request
  trước kết thúc; robots.txt có `Crawl-delay` lớn hơn thì theo robots. Mỗi bước chuyển hướng cũng là
  một request (tự theo chuyển hướng từng bước, không để httpx bắn liên tiếp).
- User-Agent TRUNG THỰC từ `CRAWLER_USER_AGENT` (.env), mẫu docs/tong-hop.md 6.2. Thiếu → lỗi.
  User-Agent giả trình duyệt ("Mozilla/…") bị từ chối: báo chặn mình thì dừng, không giả danh.
- robots.txt (urllib.robotparser; đệm theo domain trong đời client): URL bị cấm →
  `RobotsDisallowed`, không gửi request. robots.txt trả 401/403 = cấm toàn bộ (quy ước của
  urllib); 404 = cho phép; 5xx/lỗi mạng = coi như cấm (RFC 9309: không đọc được thì không cào).
  ⚠ urllib không hiểu ký tự đại diện `*`/`$` trong đường dẫn — báo dùng wildcard thì cân nhắc
  `protego` (mục 6.2).
- 429/5xx/lỗi mạng → thử lại tối đa `max_retries` lần, chờ max(Retry-After, backoff·2^k), trần
  300 s.
- 403: ném `Forbidden`; `block_after_403` lần 403 LIÊN TIẾP trên một domain → `DomainBlocked`, mọi
  request sau tới domain đó bị chặn ngay ở client. Báo chặn → dừng, báo người dùng, KHÔNG vượt chặn.
- `get_xml()`: sitemap/RSS. Nhận HTML thay XML (bẫy VnExpress: sitemap 302 → trang chủ) →
  `NotXmlError`, không coi là "sitemap rỗng" (nếu không, một báo âm thầm biến mất). Bỏ BOM đầu
  file (bẫy Dân Trí), tự giải nén `.xml.gz`.

Đồng hồ (`clock`) và `sleep` tiêm vào được → test không ngủ thật (tests/ingest/test_fetch.py).
"""
from __future__ import annotations

import gzip
import logging
import os
import time
import urllib.robotparser
from collections.abc import Callable
from typing import Self
from urllib.parse import urljoin, urlsplit

import httpx
from dotenv import load_dotenv

log = logging.getLogger(__name__)

MAX_BACKOFF = 300.0
_RETRY_STATUS = {429, 500, 502, 503, 504}
_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_XML_STARTS = (b"<?xml", b"<urlset", b"<sitemapindex", b"<rss", b"<feed", b"<rdf")


class CrawlerConfigError(RuntimeError):
    pass


class FetchError(RuntimeError):
    """Không lấy được trang (hết lượt thử lại, lỗi mạng…)."""


class Forbidden(FetchError):
    """Báo trả 403 cho một URL."""


class DomainBlocked(FetchError):
    """Báo chặn cả domain (403 liên tiếp). Dừng cào domain này, báo người dùng."""


class RobotsDisallowed(FetchError):
    """robots.txt không cho User-Agent này tải URL. Không tải, không tìm cách lách."""


class NotXmlError(FetchError):
    """Đợi XML (sitemap/RSS) nhưng nhận HTML/thứ khác — thường là bị chuyển hướng về trang chủ."""


def _user_agent_from_env() -> str:
    load_dotenv()
    ua = os.environ.get("CRAWLER_USER_AGENT", "").strip()
    if not ua:
        raise CrawlerConfigError(
            "Thiếu CRAWLER_USER_AGENT trong .env. Dùng User-Agent trung thực, ví dụ "
            "PBL-EventLake/0.1 (nghien cuu sinh vien; +mailto:<email-cua-nhom>)")
    return ua


class PoliteClient:
    def __init__(self, user_agent: str | None = None, *, min_delay: float = 2.0,
                 max_retries: int = 3, backoff: float = 5.0, block_after_403: int = 2,
                 timeout: float = 20.0, max_redirects: int = 5,
                 transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        ua = (user_agent or _user_agent_from_env()).strip()
        if ua.lower().startswith("mozilla/") or "chrome/" in ua.lower():
            raise CrawlerConfigError(
                "User-Agent trông như trình duyệt — không giả danh trình duyệt để cào. Dùng "
                "User-Agent trung thực (AGENTS.md mục 3).")
        if min_delay < 2.0:
            raise CrawlerConfigError("min_delay tối thiểu 2 giây/request/domain (AGENTS.md mục 3)")
        self.user_agent = ua
        self.min_delay = min_delay
        self.max_retries = max_retries
        self.backoff = backoff
        self.block_after_403 = block_after_403
        self.max_redirects = max_redirects
        self._clock = clock
        self._sleep = sleep
        self._http = httpx.Client(headers={"User-Agent": ua}, timeout=timeout,
                                  follow_redirects=False, transport=transport)
        self._next_ok: dict[str, float] = {}         # domain → thời điểm được gửi request kế
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._delay: dict[str, float] = {}           # domain → giãn cách (max với Crawl-delay)
        self._n403: dict[str, int] = {}
        self._blocked: set[str] = set()
        self.n_requests = 0

    # ------------------------------------------------------------------ vòng đời
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ giãn cách + gửi
    @staticmethod
    def _domain(url: str) -> str:
        return urlsplit(url).netloc.lower()

    def _wait_turn(self, domain: str) -> None:
        wait = self._next_ok.get(domain, 0.0) - self._clock()
        if wait > 0:
            self._sleep(wait)

    def _send_once(self, url: str) -> httpx.Response:
        domain = self._domain(url)
        self._wait_turn(domain)
        try:
            self.n_requests += 1
            return self._http.get(url)
        finally:
            self._next_ok[domain] = self._clock() + self._delay.get(domain, self.min_delay)

    def _send(self, url: str) -> httpx.Response:
        """Một request (không theo chuyển hướng), thử lại khi 429/5xx/lỗi mạng."""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._send_once(url)
            except httpx.TransportError as e:
                if attempt == self.max_retries:
                    raise FetchError(f"Lỗi mạng khi tải {url}: {e.__class__.__name__}: {e}") from e
                self._sleep(self._backoff_for(attempt, None))
                continue
            if resp.status_code not in _RETRY_STATUS:
                return resp
            if attempt == self.max_retries:
                raise FetchError(f"{url} trả {resp.status_code} sau {attempt + 1} lần thử")
            wait = self._backoff_for(attempt, resp.headers.get("retry-after"))
            log.warning("%s trả %s, chờ %.0f s rồi thử lại", url, resp.status_code, wait)
            self._sleep(wait)
        raise AssertionError("không tới được")

    def _backoff_for(self, attempt: int, retry_after: str | None) -> float:
        wait = self.backoff * 2 ** attempt
        if retry_after and retry_after.strip().isdigit():
            wait = max(wait, float(retry_after))
        return min(wait, MAX_BACKOFF)

    # ------------------------------------------------------------------ robots.txt
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urlsplit(url)
        domain = parts.netloc.lower()
        rp = self._robots.get(domain)
        if rp is not None:
            return rp
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            resp = self._follow(robots_url, check_robots=False)
            code = resp.status_code
        except FetchError:
            code = 599
        if code in (401, 403) or code >= 500:
            rp.disallow_all = True
            log.warning("robots.txt của %s trả %s → coi như cấm toàn bộ", domain, code)
        elif code >= 400:
            rp.allow_all = True
        else:
            rp.parse(resp.text.splitlines())
            cd = rp.crawl_delay(self.user_agent)
            if cd:
                self._delay[domain] = max(self.min_delay, float(cd))
        self._robots[domain] = rp
        return rp

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------ API cho crawler
    def _follow(self, url: str, check_robots: bool = True) -> httpx.Response:
        chain: list[httpx.Response] = []
        for _ in range(self.max_redirects + 1):
            domain = self._domain(url)
            if domain in self._blocked:
                raise DomainBlocked(f"{domain} đã bị dừng sau {self.block_after_403} lần 403 "
                                    "liên tiếp — báo người dùng, không vượt chặn")
            if check_robots and not self.allowed(url):
                raise RobotsDisallowed(f"robots.txt cấm {self.user_agent!r} tải {url}")
            resp = self._send(url)
            if resp.status_code in _REDIRECT_STATUS and "location" in resp.headers:
                chain.append(resp)
                url = urljoin(url, resp.headers["location"])
                continue
            resp.history = chain
            return resp
        raise FetchError(f"Quá {self.max_redirects} lần chuyển hướng từ {chain[0].url}")

    def get(self, url: str) -> httpx.Response:
        """GET một trang (theo chuyển hướng từng bước, mỗi bước đều giãn cách + kiểm robots).
        2xx/3xx/404… trả về để crawler tự quyết; 403 → `Forbidden` / `DomainBlocked`."""
        resp = self._follow(url)
        domain = self._domain(str(resp.url))
        if resp.status_code == 403:
            self._n403[domain] = self._n403.get(domain, 0) + 1
            if self._n403[domain] >= self.block_after_403:
                self._blocked.add(domain)
                raise DomainBlocked(f"{domain} trả 403 {self._n403[domain]} lần liên tiếp — "
                                    "dừng domain này, báo người dùng, KHÔNG vượt chặn")
            raise Forbidden(f"{url} trả 403")
        self._n403[domain] = 0
        return resp

    def get_xml(self, url: str) -> bytes:
        """Tải sitemap/RSS, trả bytes XML (đã bỏ BOM, đã gunzip). Không phải XML → `NotXmlError`."""
        resp = self.get(url)
        hops = " → ".join(f"{r.status_code} {r.url}" for r in resp.history)
        via = f" (qua chuyển hướng: {hops} → {resp.url})" if hops else ""
        if resp.status_code != 200:
            raise FetchError(f"{url} trả {resp.status_code}{via}")
        body = resp.content
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        body = body.removeprefix(b"\xef\xbb\xbf").lstrip()
        ctype = resp.headers.get("content-type", "").lower()
        head = body[:200].lower()
        if "html" in ctype or head.startswith((b"<!doctype html", b"<html")) \
                or not head.startswith(_XML_STARTS):
            raise NotXmlError(f"{url} không trả XML (content-type {ctype or '?'}, mở đầu "
                              f"{body[:40]!r}){via}. Báo có thể đã chặn/chuyển hướng sitemap — "
                              "dừng, báo người dùng.")
        return body
