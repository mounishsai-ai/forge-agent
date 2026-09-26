"""Basic sanity checks. The hidden grader instruments the fetcher to check
concurrency limits, exact visit counts, and that errors are actually
reported -- passing this file is necessary but not sufficient."""
import asyncio

from crawler import Crawler, normalize_url
from fake_site import FakeFetcher


def test_normalize_url():
    assert normalize_url("http://x/a/") == "http://x/a"
    assert normalize_url("http://x/a#frag") == "http://x/a"
    assert normalize_url("http://x/a") == "http://x/a"


def test_basic_crawl():
    site = {
        "http://x/start": (["http://x/a", "http://x/b"], False),
        "http://x/a": ([], False),
        "http://x/b": ([], False),
    }
    fetcher = FakeFetcher(site, delay=0.01)
    crawler = Crawler(fetcher, max_concurrency=2)
    report = asyncio.run(crawler.crawl("http://x/start"))
    assert set(report["pages"].keys()) == {"http://x/start", "http://x/a", "http://x/b"}
    assert report["errors"] == {}
