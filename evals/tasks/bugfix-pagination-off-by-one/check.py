import subprocess
import sys
import os


def run_visible_test(cwd):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_paginate.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_paginate.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)


def main():
    cwd = os.getcwd()
    run_visible_test(cwd)

    sys.path.insert(0, cwd)
    # Force a fresh import in case pytest already imported a cached module.
    sys.modules.pop("paginate", None)
    from paginate import paginate

    items = list(range(10))

    assert paginate(items, 1, 3) == [0, 1, 2], "page 1 should be [0,1,2]"
    assert paginate(items, 2, 3) == [3, 4, 5], "page 2 should be [3,4,5]"
    assert paginate(items, 3, 3) == [6, 7, 8], "page 3 should be [6,7,8]"
    # Last page is a partial page.
    assert paginate(items, 4, 3) == [9], f"last partial page wrong: {paginate(items, 4, 3)}"
    # Page beyond the data returns empty.
    assert paginate(items, 5, 3) == [], "page beyond data should be empty"
    # page_size larger than the whole list.
    assert paginate(items, 1, 100) == items, "oversized page_size should return everything"
    # page_size of 1 returns single items in order.
    assert paginate(items, 5, 1) == [4], f"page_size=1 page 5 wrong: {paginate(items, 5, 1)}"
    # Empty input list.
    assert paginate([], 1, 3) == [], "empty items should paginate to empty"

    print("OK")


if __name__ == "__main__":
    main()
