"""In-memory fake HTTP fetcher for testing the crawler in crawler.py --
no real network involved, so tests are fast and deterministic.
"""
from __future__ import annotations

import asyncio


class FetchError(Exception):
    """Raised by FakeFetcher.fetch() for a page marked broken."""


class FakeFetcher:
    """`site` maps an exact URL string to (links: list[str], broken: bool).

    fetch(url) looks `url` up *exactly* as given (no normalization is done
    here -- normalizing URLs before fetching, and before deciding whether a
    page has already been visited, is the crawler's job).

    - If `url` isn't a key in `site`, raises KeyError.
    - If the page is marked broken, raises FetchError.
    - Otherwise returns (status_code, links, body).

    For inspection after a crawl:
      - fetch_counts: dict[url] -> how many times fetch() was called with
        that exact url string.
      - peak_concurrency: the largest number of fetch() calls that were
        simultaneously in-flight (started but not yet returned/raised) at
        any point during the run.
    """

    def __init__(self, site: dict, delay: float = 0.03) -> None:
        self.site = site
        self.delay = delay
        self.fetch_counts: dict[str, int] = {}
        self.peak_concurrency = 0
        self._concurrent = 0

    async def fetch(self, url: str):
        if url not in self.site:
            raise KeyError(f"no such page in fake site: {url!r}")
        self.fetch_counts[url] = self.fetch_counts.get(url, 0) + 1
        self._concurrent += 1
        self.peak_concurrency = max(self.peak_concurrency, self._concurrent)
        try:
            await asyncio.sleep(self.delay)
            links, broken = self.site[url]
            if broken:
                raise FetchError(f"500 Internal Server Error fetching {url!r}")
            return 200, list(links), f"<html>body of {url}</html>"
        finally:
            self._concurrent -= 1
