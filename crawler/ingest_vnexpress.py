"""VnExpress Bronze extraction; retain metadata outside article.fck_detail."""

from bs4 import BeautifulSoup

ARTICLE_CONTENT_SELECTOR = "article.fck_detail"


def extract_raw_html(soup: BeautifulSoup) -> str:
    return str(soup)
