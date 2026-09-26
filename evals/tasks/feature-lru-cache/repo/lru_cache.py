class LRUCache:
    """
    A fixed-capacity cache that evicts the Least Recently Used entry
    when it's full and a new key needs to be inserted.

    - LRUCache(capacity): capacity must be a positive int (the max number
      of entries the cache can hold). A non-positive capacity raises
      ValueError.
    - get(key): returns the stored value for key, or raises KeyError if
      key is not present. A successful get counts as "using" the key,
      moving it to the most-recently-used position.
    - put(key, value): inserts or updates the value for key. This also
      counts as using the key (most-recently-used position). If key is
      new and inserting it would exceed capacity, evict the current
      least-recently-used entry first, then insert. Updating an existing
      key's value does not evict anything (it's not a new entry).
    - __len__(): the number of entries currently stored.
    """

    def __init__(self, capacity):
        raise NotImplementedError

    def get(self, key):
        raise NotImplementedError

    def put(self, key, value):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError
