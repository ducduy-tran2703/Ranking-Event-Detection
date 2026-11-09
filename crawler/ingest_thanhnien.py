"""Thanh Niên Bronze extraction for the shared automation pipeline."""

from bs4 import BeautifulSoup

ARTICLE_CONTENT_SELECTOR = "div.detail-content, [itemprop='articleBody']"


def extract_raw_html(soup: BeautifulSoup) -> str:
    # Title, date and authors can be outside the content element.
    return str(soup)
