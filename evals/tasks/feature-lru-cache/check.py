import os
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_lru_cache.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_lru_cache.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    sys.modules.pop("lru_cache", None)
    from lru_cache import LRUCache

    # Non-positive capacity raises ValueError.
    for bad_cap in (0, -1, -5):
        try:
            LRUCache(bad_cap)
            assert False, f"expected ValueError for capacity={bad_cap}"
        except ValueError:
            pass

    # get on missing key raises KeyError, even on an empty cache.
    cache = LRUCache(3)
    try:
        cache.get("x")
        assert False, "expected KeyError"
    except KeyError:
        pass

    # __len__ tracks entries, capped at capacity.
    cache = LRUCache(2)
    assert len(cache) == 0
    cache.put("a", 1)
    assert len(cache) == 1
    cache.put("b", 2)
    assert len(cache) == 2
    cache.put("c", 3)
    assert len(cache) == 2, "len should not exceed capacity"

    # Classic LRU eviction-order scenario.
    cache = LRUCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    cache.get("a")          # order of use now: b, c, a
    cache.put("d", 4)       # evicts "b" (least recently used)
    try:
        cache.get("b")
        assert False, "expected 'b' to be evicted"
    except KeyError:
        pass
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("d") == 4

    # Updating an existing key's value does not evict, and updates recency.
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 100)     # update, not a new entry; order of use: b, a
    assert len(cache) == 2
    assert cache.get("a") == 100
    cache.put("c", 3)       # should evict "b" (least recently used), not "a"
    try:
        cache.get("b")
        assert False, "expected 'b' to be evicted after update kept 'a' fresh"
    except KeyError:
        pass
    assert cache.get("a") == 100
    assert cache.get("c") == 3

    # capacity of 1: every put evicts the previous single entry.
    cache = LRUCache(1)
    cache.put("x", 1)
    cache.put("y", 2)
    try:
        cache.get("x")
        assert False, "expected 'x' evicted with capacity 1"
    except KeyError:
        pass
    assert cache.get("y") == 2
    assert len(cache) == 1

    # put on an existing key does NOT trigger unnecessary eviction of others
    # (only get/put on *new* keys triggers eviction pressure).
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("b", 22)  # update existing key
    assert len(cache) == 2
    assert cache.get("a") == 1
    assert cache.get("b") == 22

    print("OK")


if __name__ == "__main__":
    main()
