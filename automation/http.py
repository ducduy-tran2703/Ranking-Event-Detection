"""Thread-local sessions with a source-wide rate limiter and block detection."""
import threading
import time
from urllib.parse import urlparse

import requests

from crawler.harvester_qdnd import USER_AGENT


class SourceBlocked(RuntimeError):
    pass


class CrawlStopped(RuntimeError):
    pass


HOSTS = {
    "baochinhphu": {"baochinhphu.vn", "www.baochinhphu.vn"},
    "nhandan": {"nhandan.vn", "www.nhandan.vn", "api.nhandan.vn"},
    "dantri": {"dantri.com.vn", "www.dantri.com.vn"},
    "qdnd": {"qdnd.vn", "www.qdnd.vn"},
}


class SourceClient:
    def __init__(self, source, settings, stop):
        self.source = source
        self.settings = settings
        self.stop = stop
        self.blocked = threading.Event()
        self.lock = threading.Lock()
        self.local = threading.local()
        self.next_request = 0.0
        self.sessions = []

    def check(self):
        if self.stop.is_set():
            raise CrawlStopped("Application is shutting down")
        if self.blocked.is_set():
            raise SourceBlocked(f"{self.source}: source paused after HTTP block")

    def _wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            self.stop.wait(min(0.2, max(0, end - time.monotonic())))
        self.check()

    def _session(self):
        if not hasattr(self.local, "session"):
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
            self.local.session = session
            with self.lock:
                self.sessions.append(session)
        return self.local.session

    def get(self, url):
        for attempt in range(4):
            try:
                current = url
                for _ in range(6):
                    parsed = urlparse(current)
                    if parsed.scheme != "https" or parsed.hostname not in HOSTS[self.source]:
                        raise ValueError(f"Unexpected URL for {self.source}: {current}")
                    # Hold the lock while waiting: each actual start is spaced.
                    with self.lock:
                        self._wait(max(0, self.next_request - time.monotonic()))
                        self.next_request = time.monotonic() + self.settings.delays[self.source]
                    self.check()
                    response = self._session().get(
                        current, timeout=self.settings.timeout, allow_redirects=False)
                    if response.status_code in (403, 428, 429):
                        self.blocked.set()
                        raise SourceBlocked(f"{self.source}: HTTP {response.status_code} at {current}")
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        current = urljoin(current, response.headers["Location"])
                        response.close()
                        continue
                    response.raise_for_status()
                    return response
                raise ValueError("Too many redirects")
            except requests.RequestException as exc:
                code = exc.response.status_code if exc.response is not None else None
                if (code is not None and code < 500) or attempt == 3:
                    raise
                self._wait(2 ** (attempt + 1))

    def close(self):
        for session in self.sessions:
            session.close()
