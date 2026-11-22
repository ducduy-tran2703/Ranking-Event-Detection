"""Incremental discovery; reuse the site's existing selectors and categories.

Listing sources scan at least two consecutive pages containing only known URLs
before stopping. A page cap is reported as incomplete, never as success.
Sitemap sources scan from the previous successful scan minus an overlap.
"""
import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from crawler import harvester_baochinhphu as cp
from crawler import harvester_dantri as dt
from crawler import harvester_nhandan as nd
from crawler import harvester_qdnd as qd
from crawler import harvester_thanhnien as tn
from crawler import harvester_tuoitre as tt
from crawler import harvester_vietnamnet as vn
from crawler import harvester_vnexpress as vne
from crawler.ingest_baochinhphu import CATEGORIES as CP_CATEGORIES
from crawler.ingest_nhandan import CATEGORIES as ND_CATEGORIES


class DiscoveryIncomplete(RuntimeError):
    pass


def canonical_url(url):
    parts = urlsplit(url.strip())
    # Site article URLs do not need tracking parameters or fragments.
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def discover(source, client, known, since, settings):
    """Yield (url, category). The caller persists every yielded URL immediately."""
    if source in ("tuoitre", "thanhnien"):
        yield from _timeline_listings(source, client, known, settings)
    elif source in ("vietnamnet", "vnexpress"):
        yield from _category_listings(source, client, known, settings)
    elif source in ("baochinhphu", "nhandan"):
        yield from _listings(source, client, known, settings)
    elif source in ("dantri", "qdnd"):
        yield from _sitemaps(source, client, since)
    else:
        raise ValueError(f"Unsupported source: {source}")


def _category_listings(source, client, known, settings):
    module = vn if source == "vietnamnet" else vne
    limit = settings.max_listing_pages if known else settings.bootstrap_listing_pages
    errors = []
    for category_url, category in module.TARGET_CATEGORIES.items():
        quiet = 0
        for page in range(limit):
            client.check()
            url = module.listing_url(category_url, page)
            html = client.get(url).text
            urls = module.extract_article_urls(BeautifulSoup(html, "html.parser"), url)
            # These are full category pages, not timeline fragments: an empty
            # or unrecognized response is a failure, never an end-of-feed marker.
            if not urls:
                raise DiscoveryIncomplete(f"No recognized {source} links: {url}")
            quiet = quiet + 1 if all(u in known for u in urls) else 0
            for article_url in urls:
                yield article_url, category
            if quiet >= 2:
                break
        else:
            if known:
                errors.append(f"Reached {limit} pages: {category_url}")
    if errors:
        raise DiscoveryIncomplete("; ".join(errors))


def _timeline_listings(source, client, known, settings):
    module = tt if source == "tuoitre" else tn
    limit = settings.max_listing_pages if known else settings.bootstrap_listing_pages
    errors = []
    for category, zone in module.TARGET_CATEGORIES.items():
        quiet = 0
        for page in range(1, limit + 1):
            client.check()
            url = module.TIMELINE_TEMPLATE.format(zone_id=zone, page=page)
            html = client.get(url).text
            # An empty fragment after page 1 is an exhausted timeline. Nonempty
            # HTML without article URLs could be a challenge or a changed layout.
            if page > 1 and not html.strip():
                break
            urls = module.extract_article_urls(BeautifulSoup(html, "html.parser"))
            if not urls:
                raise DiscoveryIncomplete(f"No recognized {source} links: {url}")
            quiet = quiet + 1 if all(u in known for u in urls) else 0
            for article_url in urls:
                yield article_url, category
            if quiet >= 2:
                break
        else:
            if known:
                errors.append(f"Reached {limit} pages: {source} zone {zone}")
    if errors:
        raise DiscoveryIncomplete("; ".join(errors))


def _listings(source, client, known, settings):
    categories = CP_CATEGORIES if source == "baochinhphu" else ND_CATEGORIES
    # The first run establishes a recent baseline, not a historical backfill.
    limit = settings.max_listing_pages if known else settings.bootstrap_listing_pages
    errors = []
    for cfg in categories:
        quiet = 0
        for page in range(1, limit + 1):
            client.check()
            more = True
            if page == 1:
                soup = BeautifulSoup(client.get(cfg["category_url"]).text, "html.parser")
                urls = (cp._extract_focus_urls(soup) + cp._extract_listing_urls(soup)
                        if source == "baochinhphu" else nd._extract_ssr_urls(soup))
                if not urls:
                    raise DiscoveryIncomplete(f"No listing links: {cfg['category_url']}")
            elif source == "baochinhphu":
                response = client.get(f"{cp.BASE_URL}/timelinelist/{cfg['zone_id']}/{page}.htm")
                urls = cp._extract_stream_item_urls(BeautifulSoup(response.text, "html.parser"))
                if response.text.strip() and not urls:
                    raise DiscoveryIncomplete(f"Unrecognized listing HTML at page {page}")
            else:
                zone = cfg["zone_id"]
                response = client.get(f"{nd.API_BASE_URL}/api/morenews-zone-{zone}-{page}.html"
                                      f"?phrase=&page_size=30&sz={zone}&st=zone")
                data = response.json().get("data")
                if not isinstance(data, dict) or "contents" not in data or "load_more" not in data:
                    raise DiscoveryIncomplete("Unexpected Nhan Dan pagination response")
                urls = [urljoin(nd.BASE_URL, item["url"]) for item in data["contents"] if item.get("url")]
                more = data["load_more"]
            urls = list(dict.fromkeys(canonical_url(u) for u in urls))
            # Membership refers to the snapshot BEFORE this discovery, not links
            # just found on the preceding page (pages may repeat pinned articles).
            quiet = quiet + 1 if urls and all(u in known for u in urls) else 0
            for url in urls:
                yield url, cfg["category_label"]
            if not urls or not more or quiet >= 2:
                break
        else:
            if known:
                errors.append(f"Reached {limit} pages: {cfg['category_url']}")
    if errors:
        raise DiscoveryIncomplete("; ".join(errors))


def _sitemaps(source, client, since):
    module = dt if source == "dantri" else qd
    root = ET.fromstring(client.get(module.SITEMAP_INDEX_URL).content)
    entries = []
    for node in root.findall("sm:sitemap", module.SITEMAP_NS):
        location = node.findtext("sm:loc", namespaces=module.SITEMAP_NS)
        if not location:
            continue
        rx = dt._SITEMAP_FILENAME_DATE_RE if source == "dantri" else qd._DAILY_SITEMAP_RE
        match = rx.search(location)
        if not match:
            continue
        if source == "dantri":
            date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            relevant = (date.year, date.month) >= (since.year, since.month)
        else:
            day, month, year = match.groups()
            date = datetime(int(year), int(month), int(day)).date()
            relevant = date >= since.date()
        if relevant:
            entries.append((date, location))
    if not entries:
        raise DiscoveryIncomplete("No matching sitemap in the requested time window")
    for _, location in sorted(entries, reverse=True):
        tree = ET.fromstring(client.get(location).content)
        nodes = tree.findall("sm:url", module.SITEMAP_NS)
        if not nodes:
            raise DiscoveryIncomplete(f"Empty or unrecognized sitemap: {location}")
        for node in nodes:
            url = node.findtext("sm:loc", namespaces=module.SITEMAP_NS)
            if not url:
                continue
            url = canonical_url(url)
            slug = module._extract_first_slug(url)
            category = module.SLUG_TO_CATEGORY.get(slug)
            if source == "dantri":
                # The article timestamp is encoded in Dan Tri URLs. Avoid
                # downloading an entire month on the very first daily scan.
                stamp = re.search(r"-(\d{14})\.htm$", url)
                if stamp:
                    try:
                        published = datetime.strptime(stamp.group(1), "%Y%m%d%H%M%S").replace(tzinfo=since.tzinfo)
                        if published < since:
                            continue
                    except ValueError:
                        pass  # Unknown timestamp: retain the candidate.
                if slug == dt.SPECIAL_SLUG_THOI_SU:
                    # Inspect ggCatList AFTER downloading, keeping that HTML
                    # for Bronze instead of fetching the article twice.
                    category = dt.CHINH_TRI_CATEGORY_LABEL
            if category:
                yield url, category
