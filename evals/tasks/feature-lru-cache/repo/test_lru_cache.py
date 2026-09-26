import pytest

from lru_cache import LRUCache


def test_basic_put_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert len(cache) == 2


def test_missing_key_raises():
    cache = LRUCache(2)
    with pytest.raises(KeyError):
        cache.get("missing")


def test_eviction():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)  # evicts "a", the least recently used
    with pytest.raises(KeyError):
        cache.get("a")
    assert cache.get("b") == 2
    assert cache.get("c") == 3
