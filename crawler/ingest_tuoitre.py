"""Bronze extraction for Tuổi Trẻ, used by the shared automation pipeline."""

from bs4 import BeautifulSoup

ARTICLE_CONTENT_SELECTOR = "div.detail, article, .detail__main"


def extract_raw_html(soup: BeautifulSoup) -> str:
    # Dates and JSON-LD may live outside the article container. Retain the full
    # response like the user's original crawler so replay does not lose metadata.
    return str(soup)
