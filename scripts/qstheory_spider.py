"""Selenium-based crawler for the Qiushi Theory article catalogue.

The spider visits the catalogue page and then walks through the discovered
article links.  Each article is fetched in sequence in the same browser
session to reduce overhead.  The scraped payload is printed to stdout as a
JSON array with the article title, URL, and concatenated paragraph text.

Running the script requires a Chrome/Chromium driver available on PATH.  For
example::

    python scripts/qstheory_spider.py --max-articles 5 --headless

"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

CATALOG_URL = "https://www.qstheory.cn/qs/mulu.htm"


@dataclass
class Article:
    """Simple representation of an article scraped from Qiushi Theory."""

    title: str
    url: str
    content: str


class QiushiSpider:
    """Spider implementation that hides webdriver details from the caller."""

    def __init__(self, *, headless: bool = True, timeout: int = 15) -> None:
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        self._driver = webdriver.Chrome(options=options)
        self._wait = WebDriverWait(self._driver, timeout)

    def close(self) -> None:
        self._driver.quit()

    # Context manager helpers -------------------------------------------------
    def __enter__(self) -> "QiushiSpider":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()

    # Scraping helpers --------------------------------------------------------
    def _scrape_catalog(self) -> List[tuple[str, str]]:
        """Return a list of (title, url) pairs from the catalogue page."""

        self._driver.get(CATALOG_URL)

        # The catalogue uses standard anchor tags for each article.  We wait
        # for them to be present before iterating to make the spider resilient
        # against slow network conditions.
        locator = (By.CSS_SELECTOR, "div.list ul li a, div#allData a")
        self._wait.until(EC.presence_of_all_elements_located(locator))

        links = []
        for anchor in self._driver.find_elements(*locator):
            title = anchor.text.strip()
            url = anchor.get_attribute("href") or ""
            if not title or not url:
                continue
            # Filter out anchors that stay on the current page.
            if url.startswith("javascript:"):
                continue
            links.append((title, url))
        return links

    def _scrape_article(self, title: str, url: str) -> Article:
        """Fetch and parse a single article page."""

        self._driver.get(url)

        # Article content on Qiushi Theory is stored inside one of a handful of
        # containers.  We try a couple of common selectors in order.
        content_selectors = (
            "div.QSText div.QSArticle p",
            "div.QSArticle p",
            "div.article p",
            "div.qs-text p",
        )
        paragraphs: List[str] = []
        for css in content_selectors:
            try:
                self._wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, css)))
            except Exception:
                continue
            paragraphs = [
                element.text.strip()
                for element in self._driver.find_elements(By.CSS_SELECTOR, css)
                if element.text.strip()
            ]
            if paragraphs:
                break

        if not paragraphs:
            body_text = self._driver.find_element(By.TAG_NAME, "body").text.strip()
            paragraphs = [body_text] if body_text else []

        content = "\n".join(paragraphs)
        return Article(title=title, url=url, content=content)

    def scrape(self, *, max_articles: int | None = None) -> Sequence[Article]:
        """Scrape the catalogue and return a sequence of articles."""

        articles: List[Article] = []
        for idx, (title, url) in enumerate(self._scrape_catalog(), start=1):
            articles.append(self._scrape_article(title, url))
            if max_articles and idx >= max_articles:
                break
        return articles


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-articles",
        type=int,
        default=None,
        help="Limit the number of articles fetched from the catalogue.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser in headless mode (enabled by default).",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Disable headless mode for debugging.",
    )
    parser.set_defaults(headless=True)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)

    try:
        with QiushiSpider(headless=args.headless) as spider:
            articles = spider.scrape(max_articles=args.max_articles)
    except Exception as exc:  # pragma: no cover - runtime feedback for CLI
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    json.dump([article.__dict__ for article in articles], sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
