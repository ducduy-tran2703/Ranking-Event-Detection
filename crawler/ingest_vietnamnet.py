"""VietnamNet Bronze extraction; preserve metadata outside the article body."""

from bs4 import BeautifulSoup

ARTICLE_CONTENT_SELECTOR = "#maincontent, .maincontent"


def extract_raw_html(soup: BeautifulSoup) -> str:
    return str(soup)
