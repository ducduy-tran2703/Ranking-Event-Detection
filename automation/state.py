from datetime import datetime, timezone
from crawler.common_utils import compute_article_id
from .storage import read_json, write_json


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class SourceState:
    """One owner per source; worker threads never mutate this metadata."""
    def __init__(self, root, source):
        self.path = root / "state" / f"{source}.json"
        self.value = read_json(self.path, {"last_discovery": None, "articles": {}})

    @property
    def articles(self):
        return self.value["articles"]

    def save(self):
        write_json(self.path, self.value)

    def add(self, url, category):
        key = compute_article_id(url)
        if key not in self.articles:
            self.articles[key] = {"url": url, "category": category, "status": "pending",
                                  "attempts": 0, "updated_at": now_iso()}
            self.save()
        return key
