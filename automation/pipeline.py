from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta, timezone
from importlib import import_module
import json

from bs4 import BeautifulSoup

from crawler import harvester_dantri as dt
from process_data.clean_record import clean_record
from .discovery import discover
from .http import SourceClient, SourceBlocked, CrawlStopped
from .state import SourceState, now_iso
from .storage import read_json, write_json, write_text


class Pipeline:
    def __init__(self, settings, stop):
        self.settings = settings
        self.root = settings.data_dir
        self.stop = stop

    def article_path(self, stage, source, key):
        return self.root / stage / source / f"{key}.json"

    def process_article(self, source, key, entry, client):
        """Each task owns a distinct ID. Atomic canonical files make replay safe."""
        client.check()
        clean_path = self.article_path("clean_silver", source, key)
        if clean_path.exists():
            return "clean", None
        bronze_path = self.article_path("bronze", source, key)
        bronze = read_json(bronze_path)
        if bronze is None:
            response = client.get(entry["url"])
            soup = BeautifulSoup(response.text, "html.parser")
            ingestor = import_module(f"crawler.ingest_{source}")
            if source == "dantri":
                content = ingestor._extract_content_container(soup)
            else:
                content = soup.select_one(ingestor.ARTICLE_CONTENT_SELECTOR)
            if content is None:
                raise ValueError("Article content selector not found")
            bronze = {"url": entry["url"], "raw_html": str(content),
                      "category": entry["category"], "crawled_at": now_iso()}
            if source == "dantri" and dt._extract_first_slug(entry["url"]) == "thoi-su":
                match = dt._GG_CAT_LIST_RE.search(response.text)
                if match is None:
                    raise ValueError("Cannot classify thoi-su: ggCatList missing")
                bronze["is_chinh_tri"] = match.group(1).strip() == dt.CHINH_TRI_GGCATLIST_VALUE
            write_json(bronze_path, bronze)
        if bronze.get("is_chinh_tri") is False:
            return "rejected", "not_target_category"
        transformer = import_module(f"crawler.silver_transformer_{source}")
        silver = transformer.transform_record(bronze)
        if silver is None:
            return "rejected", "silver_extraction_failed_or_unsupported_type"
        # Use one spelling across all sources without altering legacy scripts.
        if silver["category"].casefold() == "khoa học - công nghệ":
            silver["category"] = "Khoa học - Công nghệ"
        write_json(self.article_path("silver", source, key), silver)
        cleaned, reason = clean_record(silver)
        if cleaned is None:
            return "rejected", reason
        write_json(clean_path, cleaned)
        return "clean", None

    def run_source(self, source, job_id, report, retry_failed=False):
        state = SourceState(self.root, source)
        client = SourceClient(source, self.settings, self.stop)
        stats = {"status": "running", "phase": "discovery", "discovered": 0,
                 "processed": 0, "clean": 0, "rejected": 0, "failed": 0,
                 "errors": []}
        touched = []
        try:
            report(dict(stats))
            if retry_failed:
                for entry in state.articles.values():
                    if entry["status"] == "failed":
                        entry.update(status="pending", attempts=0)
                state.save()
            start = datetime.now(timezone.utc)
            last = state.value["last_discovery"]
            since = (datetime.fromisoformat(last) - timedelta(hours=self.settings.overlap_hours)
                     if last else start - timedelta(hours=self.settings.initial_lookback_hours))
            # Sitemap calendar names and URL timestamps use Vietnamese time.
            from zoneinfo import ZoneInfo
            since = since.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
            known = {entry["url"] for entry in state.articles.values()}
            stats["discovery_mode"] = ("bootstrap_recent_pages" if not known and source in ("baochinhphu", "nhandan")
                                       else "incremental")
            discovery_complete = False
            try:
                for url, category in discover(source, client, known, since, self.settings):
                    before = len(state.articles)
                    state.add(url, category)
                    stats["discovered"] += len(state.articles) - before
                    if stats["discovered"] and stats["discovered"] % 20 == 0:
                        report(dict(stats))
                state.value["last_discovery"] = start.isoformat()
                state.save()
                discovery_complete = True
            except (SourceBlocked, CrawlStopped):
                raise
            except Exception as exc:
                stats["errors"].append(f"discovery: {type(exc).__name__}: {exc}")
            stats["phase"] = "processing"
            report(dict(stats))
            candidates = iter((key, dict(entry)) for key, entry in state.articles.items()
                              if entry["status"] in ("pending", "failed")
                              and entry["attempts"] < self.settings.max_article_attempts)
            with ThreadPoolExecutor(max_workers=self.settings.workers_per_source,
                                    thread_name_prefix=source) as pool:
                pending = {}

                def fill():
                    while len(pending) < self.settings.workers_per_source:
                        client.check()
                        item = next(candidates, None)
                        if item is None:
                            break
                        key, entry = item
                        pending[pool.submit(self.process_article, source, key, entry, client)] = key

                halted = None
                fill()
                while pending:
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        key = pending.pop(future)
                        entry = state.articles[key]
                        try:
                            status, reason = future.result()
                            entry.update(status=status, last_error=reason, updated_at=now_iso())
                            stats[status] += 1
                            touched.append(key)
                        except (SourceBlocked, CrawlStopped) as exc:
                            halted = exc
                        except Exception as exc:
                            entry.update(status="failed", attempts=entry["attempts"] + 1,
                                         last_error=f"{type(exc).__name__}: {exc}", updated_at=now_iso())
                            stats["failed"] += 1
                            if len(stats["errors"]) < 20:
                                stats["errors"].append(f"{entry['url']}: {entry['last_error']}")
                            touched.append(key)
                        state.save()
                        stats["processed"] += 1
                        report(dict(stats))
                    if not halted:
                        try:
                            fill()
                        except (SourceBlocked, CrawlStopped) as exc:
                            halted = exc
                if halted:
                    raise halted
            exhausted = sum(e["status"] == "failed" and e["attempts"] >= self.settings.max_article_attempts
                            for e in state.articles.values())
            stats["exhausted"] = exhausted
            stats["status"] = ("completed" if discovery_complete and not stats["failed"] and not exhausted
                               else "partial")
        except SourceBlocked as exc:
            stats["status"] = "blocked"
            stats["errors"].append(str(exc))
        except CrawlStopped as exc:
            stats["status"] = "interrupted"
            stats["errors"].append(str(exc))
        except Exception as exc:
            stats["status"] = "failed"
            stats["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            client.close()
            # Canonical article files survive even if a crash interrupts exports.
            # Export is replaced atomically and contains each touched ID once.
            for stage in ("bronze", "silver", "clean_silver"):
                records = [read_json(self.article_path(stage, source, key)) for key in dict.fromkeys(touched)]
                text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records if r is not None)
                write_text(self.root / "jobs" / job_id / stage / f"{source}.jsonl", text)
            rejects = [{"article_id": key, "source": source, "url": state.articles[key]["url"],
                        "reason": state.articles[key].get("last_error")}
                       for key in dict.fromkeys(touched) if state.articles[key]["status"] == "rejected"]
            write_text(self.root / "jobs" / job_id / "rejects" / f"{source}.jsonl",
                       "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rejects))
            stats["phase"] = "finished"
            report(dict(stats))
        return stats

    def run(self, job, report, retry_failed=False):
        with ThreadPoolExecutor(max_workers=len(job["sources"]), thread_name_prefix="source") as pool:
            futures = {pool.submit(self.run_source, source, job["id"],
                                   lambda value, s=source: report(s, value), retry_failed): source
                       for source in job["sources"]}
            results = {}
            for future, source in futures.items():
                try:
                    results[source] = future.result()
                except Exception as exc:
                    results[source] = {"status": "failed", "errors": [str(exc)]}
                    report(source, results[source])
        return results
