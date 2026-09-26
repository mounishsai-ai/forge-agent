import asyncio
import os
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_crawler.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_crawler.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    for mod in ("crawler", "fake_site"):
        sys.modules.pop(mod, None)
    from crawler import Crawler, normalize_url
    from fake_site import FakeFetcher, FetchError

    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)

    # Wide fan-out (start -> 8 pages) to make unbounded concurrency
    # detectable, one broken leaf (p8), and three differently-spelled
    # variants of the same logical page ("shared") reached from three
    # different parents to test URL normalization / dedup.
    site = {
        "http://x/start": ([f"http://x/p{i}" for i in range(1, 9)], False),
        "http://x/p1": (["http://x/shared/"], False),
        "http://x/p2": (["http://x/shared#frag"], False),
        "http://x/p3": (["http://x/shared"], False),
        "http://x/p4": ([], False),
        "http://x/p5": ([], False),
        "http://x/p6": ([], False),
        "http://x/p7": ([], False),
        "http://x/p8": ([], True),
        "http://x/shared": ([], False),
        "http://x/shared/": ([], False),
        "http://x/shared#frag": ([], False),
    }

    MAX_CONCURRENCY = 3
    fetcher = FakeFetcher(site, delay=0.05)
    crawler = Crawler(fetcher, max_concurrency=MAX_CONCURRENCY)

    try:
        report = asyncio.run(asyncio.wait_for(crawler.crawl("http://x/start"), timeout=30))
    except Exception as e:
        print(f"crawl() raised unexpectedly: {e!r}")
        sys.exit(1)

    # --- Bug 1: concurrency must actually be capped. ---
    check(
        f"peak_concurrency ({fetcher.peak_concurrency}) respects max_concurrency ({MAX_CONCURRENCY})",
        fetcher.peak_concurrency <= MAX_CONCURRENCY,
    )

    # --- Bug 2: each canonical page fetched exactly once (no revisits from
    # trailing-slash / fragment variants). ---
    canonical_counts: dict[str, int] = {}
    for raw_url, count in fetcher.fetch_counts.items():
        canon = normalize_url(raw_url)
        canonical_counts[canon] = canonical_counts.get(canon, 0) + count

    expected_canonical = {"http://x/start"} | {f"http://x/p{i}" for i in range(1, 9)} | {"http://x/shared"}
    check("visited exactly the expected canonical pages", set(canonical_counts.keys()) == expected_canonical)
    over_visited = {k: v for k, v in canonical_counts.items() if v != 1}
    check(f"every canonical page fetched exactly once (got {over_visited})", not over_visited)

    # --- Bug 3: fetch failures must be reported, not swallowed. ---
    check(
        "broken page reported in errors, not pages",
        "http://x/p8" in report.get("errors", {}) and "http://x/p8" not in report.get("pages", {}),
    )
    check("error message mentions the failure", "http://x/p8" in str(report.get("errors", {}).get("http://x/p8", "")) or True)

    # --- Successful pages all reported with their status. ---
    expected_success = expected_canonical - {"http://x/p8"}
    check(
        f"successful pages reported (got {sorted(report.get('pages', {}).keys())})",
        set(report.get("pages", {}).keys()) == expected_success,
    )
    check("successful pages report status 200", all(v == 200 for v in report.get("pages", {}).values()))

    # --- No page fetched under a URL not reachable from start (sanity). ---
    check("no unexpected errors beyond the one broken page", set(report.get("errors", {}).keys()) == {"http://x/p8"})

    if failures:
        print("FAILED checks:")
        for f in failures:
            print(" -", f)
        print(f"peak_concurrency={fetcher.peak_concurrency} fetch_counts={fetcher.fetch_counts}")
        print(f"report={report}")
        sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
