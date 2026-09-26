"""A small async site crawler built on top of an injected fetcher (see
fake_site.py for tests / FakeFetcher; in production this would wrap a real
async HTTP client).

Someone filed this complaint about it:

    "Crawls are slow to finish and our test site's fake server logs way
    more hits than there are actual pages -- feels like it's hammering the
    same page repeatedly. Also I swear I saw a traceback flash by once but
    the crawl 'finished successfully' and the report showed no errors at
    all, so now I don't trust the report."

Nobody has dug further than that. The intended behavior (also see
Crawler.crawl's docstring below) is:

  - never have more than `max_concurrency` fetches in flight at once,
  - fetch every distinct page exactly once, where "distinct" is decided
    after normalizing the URL with normalize_url() below (so trailing
    slashes and #fragments don't create duplicate visits),
  - never lose a fetch failure: every page that errors must show up in the
    returned report's "errors", not just vanish.
"""
from __future__ import annotations

import asyncio


def normalize_url(url: str) -> str:
    """Canonicalize a URL for visited-tracking and for fetching: drop any
    #fragment, and strip a single trailing slash (but never turn a URL into
    the empty string)."""
    url = url.split("#", 1)[0]
    if url.endswith("/") and len(url) > 1:
        url = url[:-1]
    return url


class Crawler:
    """
    crawl(start_url) -> {"pages": {normalized_url: status_code},
                          "errors": {normalized_url: str(exception)}}

    Starting from start_url, follows every link found in a fetched page's
    link list, breadth-first, until the frontier is exhausted. Each
    distinct normalized URL is fetched at most once. At most
    self.max_concurrency fetches run concurrently. A page whose fetch
    raises is recorded under "errors" (not "pages"), and its own links (it
    has none, since the fetch failed) are simply not followed -- but the
    failure itself must never be lost.
    """

    def __init__(self, fetcher, max_concurrency: int = 5) -> None:
        self.fetcher = fetcher
        self.max_concurrency = max_concurrency

    async def crawl(self, start_url: str) -> dict:
        pages: dict[str, int] = {}
        errors: dict[str, str] = {}
        queue: asyncio.Queue = asyncio.Queue()
        seen = {start_url}
        await queue.put(start_url)

        async def worker() -> None:
            while True:
                url = await queue.get()
                try:
                    status, links, body = await self.fetcher.fetch(url)
                    pages[url] = status
                    for link in links:
                        if link not in seen:
                            seen.add(link)
                            await queue.put(link)
                except Exception:
                    pass
                finally:
                    queue.task_done()

        # NOTE: fixed pool size -- max_concurrency is accepted by __init__
        # but never actually consulted anywhere in here.
        workers = [asyncio.create_task(worker()) for _ in range(20)]
        await queue.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        return {"pages": pages, "errors": errors}
